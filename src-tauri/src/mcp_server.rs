/// Local HTTP server that exposes Proton Drive tools to Claude Desktop via MCP.
///
/// Claude Desktop (and other MCP clients) can connect in two ways:
///
/// 1. HTTP transport (preferred, no install needed):
///    Add to claude_desktop_config.json:
///      { "mcpServers": { "proton-drive": { "url": "http://127.0.0.1:37242/mcp" } } }
///
/// 2. stdio transport (legacy, via mcp/proton-drive-mcp Python bridge):
///    The bridge reads the port from $TMPDIR/proton-drive-mcp.port.
///    Port is now fixed to 37242 so the bridge can be pre-configured too.
use std::collections::HashMap;
use std::sync::{mpsc, Arc, Mutex};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use axum::{
    extract::State,
    http::{HeaderMap, HeaderValue, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use tauri::{AppHandle, Emitter};

pub const FIXED_PORT: u16 = 37242;

static CALL_ID: AtomicU64 = AtomicU64::new(1);

/// Shared map: call-id → channel sender that the HTTP handler waits on.
pub type PendingCalls = Arc<Mutex<HashMap<String, mpsc::SyncSender<Result<String, String>>>>>;

#[derive(Clone)]
struct ServerState {
    app_handle: AppHandle,
    pending: PendingCalls,
}

#[derive(Deserialize)]
struct LegacyToolCallRequest {
    name: String,
    #[serde(default)]
    arguments: serde_json::Value,
}

const TOOLS: &[(&str, &str)] = &[
    (
        "list_devices",
        "List the Linux computers synced to this Proton Drive account.",
    ),
    (
        "get_drive_status",
        "Check whether the Proton Drive desktop client is running and the Claude API key is configured.",
    ),
];

fn tool_list_json() -> Vec<serde_json::Value> {
    TOOLS
        .iter()
        .map(|(name, description)| {
            serde_json::json!({
                "name": name,
                "description": description,
                "inputSchema": { "type": "object", "properties": {}, "required": [] }
            })
        })
        .collect()
}

/// Dispatch a tool call through the WebView and block until the result arrives.
async fn dispatch_tool(
    state: &ServerState,
    name: &str,
    arguments: serde_json::Value,
) -> Result<String, String> {
    let call_id = CALL_ID.fetch_add(1, Ordering::SeqCst).to_string();
    let (tx, rx) = mpsc::sync_channel::<Result<String, String>>(1);
    state.pending.lock().unwrap().insert(call_id.clone(), tx);

    let _ = state.app_handle.emit(
        "mcp://tool-call",
        serde_json::json!({ "id": call_id, "name": name, "arguments": arguments }),
    );

    tokio::task::spawn_blocking(move || {
        rx.recv_timeout(Duration::from_secs(30))
            .unwrap_or(Err("tool call timed out".to_string()))
    })
    .await
    .unwrap_or(Err("spawn_blocking failed".to_string()))
}

// ---------------------------------------------------------------------------
// MCP Streamable HTTP transport  (POST /mcp)
// Claude Desktop config: { "url": "http://127.0.0.1:37242/mcp" }
// ---------------------------------------------------------------------------

fn cors_headers() -> HeaderMap {
    let mut h = HeaderMap::new();
    h.insert("Access-Control-Allow-Origin", HeaderValue::from_static("*"));
    h.insert(
        "Access-Control-Allow-Headers",
        HeaderValue::from_static("content-type, authorization"),
    );
    h
}

async fn mcp_options() -> impl IntoResponse {
    (StatusCode::NO_CONTENT, cors_headers())
}

async fn mcp_jsonrpc(
    State(state): State<ServerState>,
    Json(req): Json<serde_json::Value>,
) -> impl IntoResponse {
    let id = req.get("id").cloned().unwrap_or(serde_json::Value::Null);
    let method = req
        .get("method")
        .and_then(|m| m.as_str())
        .unwrap_or("")
        .to_string();
    let params = req
        .get("params")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let body: serde_json::Value = match method.as_str() {
        "initialize" => serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": { "tools": {} },
                "serverInfo": { "name": "proton-drive", "version": "2.0.0" }
            }
        }),

        "tools/list" => serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": { "tools": tool_list_json() }
        }),

        "tools/call" => {
            let name = params
                .get("name")
                .and_then(|n| n.as_str())
                .unwrap_or("")
                .to_string();
            let arguments = params
                .get("arguments")
                .cloned()
                .unwrap_or(serde_json::json!({}));

            match dispatch_tool(&state, &name, arguments).await {
                Ok(text) => serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "result": { "content": [{ "type": "text", "text": text }] }
                }),
                Err(e) => serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32603, "message": e }
                }),
            }
        }

        "ping" => serde_json::json!({ "jsonrpc": "2.0", "id": id, "result": {} }),

        // Notifications have no id and expect no response — return empty 202
        _ if id.is_null() => serde_json::json!(null),

        _ => serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": { "code": -32601, "message": format!("Method not found: {method}") }
        }),
    };

    // Notifications: 202 Accepted, no body
    if body.is_null() {
        return (StatusCode::ACCEPTED, cors_headers(), Json(serde_json::json!({}))).into_response();
    }

    (StatusCode::OK, cors_headers(), Json(body)).into_response()
}

// ---------------------------------------------------------------------------
// Legacy relay endpoints (used by mcp/proton-drive-mcp Python bridge)
// ---------------------------------------------------------------------------

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "ok": true }))
}

async fn legacy_list_tools() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "tools": tool_list_json() }))
}

async fn legacy_call_tool(
    State(state): State<ServerState>,
    Json(req): Json<LegacyToolCallRequest>,
) -> Json<serde_json::Value> {
    match dispatch_tool(&state, &req.name, req.arguments).await {
        Ok(text) => Json(serde_json::json!({
            "content": [{ "type": "text", "text": text }]
        })),
        Err(e) => Json(serde_json::json!({
            "error": { "code": -32603, "message": e }
        })),
    }
}

// ---------------------------------------------------------------------------

pub async fn start(app_handle: AppHandle, pending: PendingCalls) {
    let addr = format!("127.0.0.1:{FIXED_PORT}");
    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[MCP] bind on {addr} failed: {e}");
            return;
        }
    };

    // Write port file so the Python bridge can connect (backward compat).
    let port_file = std::env::temp_dir().join("proton-drive-mcp.port");
    let _ = std::fs::write(&port_file, FIXED_PORT.to_string());

    println!("[MCP] listening on {addr}  (HTTP: http://{addr}/mcp)");

    let router = Router::new()
        .route("/health", get(health))
        // MCP Streamable HTTP transport — Claude Desktop HTTP config
        .route("/mcp", post(mcp_jsonrpc))
        .route("/mcp", axum::routing::options(mcp_options))
        // Legacy relay for the Python stdio bridge
        .route("/mcp/tools", get(legacy_list_tools))
        .route("/mcp/tools/call", post(legacy_call_tool))
        .with_state(ServerState { app_handle, pending });

    if let Err(e) = axum::serve(listener, router).await {
        eprintln!("[MCP] server error: {e}");
    }
}

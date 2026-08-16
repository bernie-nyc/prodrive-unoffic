/// Local HTTP server that exposes Proton Drive tools to Claude Desktop via MCP.
///
/// Claude Desktop (and other MCP clients) connect to this server through the
/// companion script at `mcp/proton-drive-mcp`, which bridges the MCP stdio
/// transport to this HTTP API.  The server binds on a random localhost port
/// and writes it to `$TMPDIR/proton-drive-mcp.port` so the script can find it.
use std::collections::HashMap;
use std::sync::{mpsc, Arc, Mutex};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use axum::{extract::State, routing::{get, post}, Json, Router};
use serde::{Deserialize, Serialize};
use tauri::AppHandle;

static CALL_ID: AtomicU64 = AtomicU64::new(1);

/// Shared map: call-id → channel sender that the HTTP handler waits on.
pub type PendingCalls = Arc<Mutex<HashMap<String, mpsc::SyncSender<Result<String, String>>>>>;

#[derive(Clone)]
struct ServerState {
    app_handle: AppHandle,
    pending: PendingCalls,
}

#[derive(Deserialize)]
struct ToolCallRequest {
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

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({ "ok": true }))
}

async fn list_tools() -> Json<serde_json::Value> {
    let tools: Vec<serde_json::Value> = TOOLS
        .iter()
        .map(|(name, description)| {
            serde_json::json!({
                "name": name,
                "description": description,
                "inputSchema": { "type": "object", "properties": {}, "required": [] }
            })
        })
        .collect();
    Json(serde_json::json!({ "tools": tools }))
}

async fn call_tool(
    State(state): State<ServerState>,
    Json(req): Json<ToolCallRequest>,
) -> Json<serde_json::Value> {
    let call_id = CALL_ID.fetch_add(1, Ordering::SeqCst).to_string();

    let (tx, rx) = mpsc::sync_channel::<Result<String, String>>(1);
    state.pending.lock().unwrap().insert(call_id.clone(), tx);

    let _ = state.app_handle.emit(
        "mcp://tool-call",
        serde_json::json!({ "id": call_id, "name": req.name, "arguments": req.arguments }),
    );

    let outcome = tokio::task::spawn_blocking(move || {
        rx.recv_timeout(Duration::from_secs(30))
    })
    .await;

    match outcome {
        Ok(Ok(Ok(text))) => Json(serde_json::json!({
            "content": [{ "type": "text", "text": text }]
        })),
        Ok(Ok(Err(e))) => Json(serde_json::json!({
            "error": { "code": -32603, "message": e }
        })),
        _ => Json(serde_json::json!({
            "error": { "code": -32603, "message": "tool call timed out or failed" }
        })),
    }
}

pub async fn start(app_handle: AppHandle, pending: PendingCalls) {
    let listener = match tokio::net::TcpListener::bind("127.0.0.1:0").await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("[MCP] bind failed: {e}");
            return;
        }
    };

    let port = match listener.local_addr() {
        Ok(a) => a.port(),
        Err(e) => {
            eprintln!("[MCP] local_addr failed: {e}");
            return;
        }
    };

    let port_file = std::env::temp_dir().join("proton-drive-mcp.port");
    if let Err(e) = std::fs::write(&port_file, port.to_string()) {
        eprintln!("[MCP] could not write port file: {e}");
    }
    println!("[MCP] listening on 127.0.0.1:{port}");

    let router = Router::new()
        .route("/health", get(health))
        .route("/mcp/tools", get(list_tools))
        .route("/mcp/tools/call", post(call_tool))
        .with_state(ServerState { app_handle, pending });

    if let Err(e) = axum::serve(listener, router).await {
        eprintln!("[MCP] server error: {e}");
    }
}

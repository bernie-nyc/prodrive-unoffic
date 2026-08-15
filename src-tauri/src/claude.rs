use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::fs;
use tauri::Manager;

const API_ENDPOINT: &str = "https://api.anthropic.com/v1/messages";
const API_VERSION: &str = "2023-06-01";
const MODEL: &str = "claude-sonnet-5";
const MAX_TOKENS: u32 = 4096;
const KEY_FILENAME: &str = "claude-api-key";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Serialize)]
struct ApiRequest<'a> {
    model: &'a str,
    max_tokens: u32,
    messages: &'a [ChatMessage],
}

#[derive(Debug, Deserialize)]
struct ApiContent {
    #[serde(rename = "type")]
    kind: String,
    text: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ApiResponse {
    content: Vec<ApiContent>,
}

fn key_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app.path().app_data_dir().map_err(|e| format!("cannot resolve data dir: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("cannot create data dir: {e}"))?;
    Ok(dir.join(KEY_FILENAME))
}

#[tauri::command]
pub async fn claude_set_api_key(app: tauri::AppHandle, key: String) -> Result<(), String> {
    let path = key_path(&app)?;
    fs::write(&path, key.trim()).map_err(|e| format!("cannot write key: {e}"))
}

#[tauri::command]
pub async fn claude_get_key_configured(app: tauri::AppHandle) -> bool {
    key_path(&app)
        .map(|p| {
            p.exists()
                && fs::read_to_string(&p)
                    .map(|s| !s.trim().is_empty())
                    .unwrap_or(false)
        })
        .unwrap_or(false)
}

#[tauri::command]
pub async fn claude_clear_api_key(app: tauri::AppHandle) -> Result<(), String> {
    let path = key_path(&app)?;
    if path.exists() {
        fs::remove_file(&path).map_err(|e| format!("cannot remove key: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
pub async fn claude_chat(
    app: tauri::AppHandle,
    messages: Vec<ChatMessage>,
) -> Result<String, String> {
    let path = key_path(&app)?;
    let key = fs::read_to_string(&path)
        .map(|s| s.trim().to_string())
        .map_err(|_| "API key not configured — set it via the Claude panel".to_string())?;

    if key.is_empty() {
        return Err("API key not configured".to_string());
    }

    let client = Client::new();
    let body = ApiRequest {
        model: MODEL,
        max_tokens: MAX_TOKENS,
        messages: &messages,
    };

    let resp = client
        .post(API_ENDPOINT)
        .header("x-api-key", &key)
        .header("anthropic-version", API_VERSION)
        .header("content-type", "application/json")
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("API error {status}: {body}"));
    }

    let api_resp: ApiResponse = resp
        .json()
        .await
        .map_err(|e| format!("parse error: {e}"))?;

    api_resp
        .content
        .into_iter()
        .filter(|c| c.kind == "text")
        .filter_map(|c| c.text)
        .next()
        .ok_or_else(|| "empty response from API".to_string())
}

#!/usr/bin/env python3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBCLIENTS_DIR = REPO_ROOT / "WebClients"
MAIN_CONTAINER_PATH = WEBCLIENTS_DIR / "applications/drive/src/app/containers/MainContainer.tsx"

BRIDGE_FILENAME = "ProtonDriveClaudeBridge.tsx"

BRIDGE_SOURCE = """import { useCallback, useEffect, useRef, useState } from 'react';

import { DeviceType, getDrive } from '@proton/drive';

type TauriCore = {
    invoke<T = unknown>(command: string, args?: Record<string, unknown>): Promise<T>;
};
type TauriEvent = {
    listen<T = unknown>(
        event: string,
        handler: (e: { payload: T }) => void
    ): Promise<() => void>;
};

type ChatMessage = { role: 'user' | 'assistant'; content: string };
type McpToolCall = { id: string; name: string; arguments: Record<string, unknown> };

const getTauri = () =>
    (window as unknown as { __TAURI__?: { core?: TauriCore; event?: TauriEvent } }).__TAURI__;

const HISTORY_KEY = 'pdl:claude-history';

const panelStyle: React.CSSProperties = {
    position: 'fixed',
    bottom: 72,
    right: 24,
    zIndex: 9998,
    width: 360,
    maxHeight: '60vh',
    display: 'flex',
    flexDirection: 'column',
    background: 'var(--background-norm, #1c1b29)',
    color: 'var(--text-norm, #e2e0ff)',
    borderRadius: 12,
    boxShadow: '0 4px 32px rgba(0,0,0,.45)',
    fontFamily: 'var(--font-family, sans-serif)',
    fontSize: 13,
    overflow: 'hidden',
    border: '1px solid var(--border-norm, #2d2b45)',
};

const buttonBase: React.CSSProperties = {
    position: 'fixed',
    bottom: 24,
    right: 24,
    zIndex: 9999,
    background: '#6d4aff',
    color: '#fff',
    border: 'none',
    borderRadius: 28,
    padding: '10px 18px',
    cursor: 'pointer',
    fontSize: 13,
    fontFamily: 'var(--font-family, sans-serif)',
    boxShadow: '0 2px 12px rgba(0,0,0,.3)',
};

export const ProtonDriveClaudeBridge = () => {
    const [open, setOpen] = useState(false);
    const [keyConfigured, setKeyConfigured] = useState<boolean | null>(null);
    const [apiKeyInput, setApiKeyInput] = useState('');
    const [messages, setMessages] = useState<ChatMessage[]>(() => {
        try {
            return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        } catch {
            return [];
        }
    });
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const bottomRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const tauri = getTauri();
        if (!tauri?.core) return;
        void tauri.core
            .invoke<boolean>('claude_get_key_configured')
            .then(setKeyConfigured)
            .catch(() => setKeyConfigured(false));
    }, [open]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, loading]);

    useEffect(() => {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-50)));
    }, [messages]);

    const saveKey = useCallback(async () => {
        const tauri = getTauri();
        if (!tauri?.core || !apiKeyInput.trim()) return;
        try {
            await tauri.core.invoke('claude_set_api_key', { key: apiKeyInput.trim() });
            setKeyConfigured(true);
            setApiKeyInput('');
            setError('');
        } catch (e) {
            setError(String(e));
        }
    }, [apiKeyInput]);

    const clearKey = useCallback(async () => {
        const tauri = getTauri();
        if (!tauri?.core) return;
        try {
            await tauri.core.invoke('claude_clear_api_key');
            setKeyConfigured(false);
            setMessages([]);
        } catch (e) {
            setError(String(e));
        }
    }, []);

    const send = useCallback(async () => {
        const text = input.trim();
        if (!text || loading) return;
        const tauri = getTauri();
        if (!tauri?.core) return;

        const next: ChatMessage[] = [...messages, { role: 'user', content: text }];
        setMessages(next);
        setInput('');
        setLoading(true);
        setError('');

        try {
            const reply = await tauri.core.invoke<string>('claude_chat', { messages: next });
            setMessages([...next, { role: 'assistant', content: reply }]);
        } catch (e) {
            setError(String(e));
        } finally {
            setLoading(false);
        }
    }, [input, loading, messages]);

    const handleMcpTool = useCallback(async (name: string, args: Record<string, unknown>): Promise<string> => {
        if (name === 'list_devices') {
            const drive = getDrive();
            const devices: Array<{ name: string; id: string }> = [];
            for await (const device of drive.iterateDevices(DeviceType.Device)) {
                devices.push({ name: device.device.name, id: device.device.id });
            }
            return JSON.stringify(devices);
        }
        if (name === 'get_drive_status') {
            const tauri = getTauri();
            const keyOk = tauri?.core
                ? await tauri.core.invoke<boolean>('claude_get_key_configured').catch(() => false)
                : false;
            return JSON.stringify({ running: true, claudeKeyConfigured: keyOk });
        }
        throw new Error(`Unknown tool: ${name}`);
    }, []);

    useEffect(() => {
        const tauri = getTauri();
        if (!tauri?.event) return;
        let unlisten: (() => void) | undefined;
        void tauri.event
            .listen<McpToolCall>('mcp://tool-call', async ({ payload }) => {
                const { id, name, arguments: mcpArgs } = payload;
                const tauriCore = getTauri()?.core;
                if (!tauriCore) return;
                try {
                    const result = await handleMcpTool(name, mcpArgs);
                    await tauriCore.invoke('mcp_tool_result', { id, result });
                } catch (e) {
                    await tauriCore.invoke('mcp_tool_result', { id, error: String(e) });
                }
            })
            .then((u) => { unlisten = u; });
        return () => { unlisten?.(); };
    }, [handleMcpTool]);

    return (
        <>
            <button
                onClick={() => setOpen((o) => !o)}
                style={buttonBase}
                title="Claude AI assistant"
            >
                ✦ {open ? 'Close' : 'Claude'}
            </button>

            {open && (
                <div style={panelStyle}>
                    {/* Header */}
                    <div
                        style={{
                            padding: '12px 16px',
                            borderBottom: '1px solid var(--border-norm, #2d2b45)',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                        }}
                    >
                        <span style={{ fontWeight: 600, color: '#c4b5fd' }}>✦ Claude</span>
                        {keyConfigured && (
                            <button
                                onClick={() => void clearKey()}
                                title="Remove API key"
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    color: 'var(--text-weak, #888)',
                                    cursor: 'pointer',
                                    fontSize: 11,
                                    padding: 0,
                                }}
                            >
                                remove key
                            </button>
                        )}
                    </div>

                    {/* Key setup */}
                    {keyConfigured === false && (
                        <div style={{ padding: 16 }}>
                            <p style={{ margin: '0 0 10px', color: 'var(--text-weak, #aaa)', lineHeight: 1.5 }}>
                                Enter your Anthropic API key to enable Claude:
                            </p>
                            <input
                                type="password"
                                value={apiKeyInput}
                                onChange={(e) => setApiKeyInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') void saveKey();
                                }}
                                placeholder="sk-ant-..."
                                style={{
                                    width: '100%',
                                    boxSizing: 'border-box',
                                    padding: '8px 10px',
                                    background: 'var(--field-background, #2a2840)',
                                    border: '1px solid var(--field-border, #3d3a5c)',
                                    borderRadius: 6,
                                    color: 'var(--field-norm, #e2e0ff)',
                                    fontSize: 13,
                                    marginBottom: 8,
                                    outline: 'none',
                                }}
                            />
                            {error && (
                                <p style={{ color: '#ff6b6b', fontSize: 12, margin: '0 0 8px' }}>{error}</p>
                            )}
                            <button
                                onClick={() => void saveKey()}
                                style={{
                                    background: '#6d4aff',
                                    color: '#fff',
                                    border: 'none',
                                    borderRadius: 6,
                                    padding: '8px 16px',
                                    cursor: 'pointer',
                                    fontSize: 13,
                                }}
                            >
                                Save key
                            </button>
                        </div>
                    )}

                    {/* Chat */}
                    {keyConfigured === true && (
                        <>
                            <div
                                style={{
                                    flex: 1,
                                    overflowY: 'auto',
                                    padding: '12px 14px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 10,
                                }}
                            >
                                {messages.length === 0 && (
                                    <p
                                        style={{
                                            color: 'var(--text-weak, #666)',
                                            textAlign: 'center',
                                            margin: '20px 0',
                                            lineHeight: 1.5,
                                        }}
                                    >
                                        Ask anything about your Proton Drive files.
                                    </p>
                                )}
                                {messages.map((m, i) => (
                                    <div
                                        key={i}
                                        style={{
                                            alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                            maxWidth: '85%',
                                            padding: '8px 12px',
                                            borderRadius:
                                                m.role === 'user'
                                                    ? '12px 12px 4px 12px'
                                                    : '12px 12px 12px 4px',
                                            background:
                                                m.role === 'user'
                                                    ? '#6d4aff'
                                                    : 'var(--background-strong, #2a2840)',
                                            color: m.role === 'user' ? '#fff' : 'var(--text-norm, #e2e0ff)',
                                            lineHeight: 1.5,
                                            whiteSpace: 'pre-wrap',
                                            wordBreak: 'break-word',
                                        }}
                                    >
                                        {m.content}
                                    </div>
                                ))}
                                {loading && (
                                    <div
                                        style={{
                                            alignSelf: 'flex-start',
                                            color: 'var(--text-weak, #888)',
                                            fontStyle: 'italic',
                                        }}
                                    >
                                        thinking…
                                    </div>
                                )}
                                {error && (
                                    <div
                                        style={{
                                            alignSelf: 'flex-start',
                                            color: '#ff6b6b',
                                            background: 'rgba(255,80,80,.08)',
                                            padding: '8px 12px',
                                            borderRadius: 8,
                                            maxWidth: '90%',
                                        }}
                                    >
                                        {error}
                                    </div>
                                )}
                                <div ref={bottomRef} />
                            </div>

                            {/* Input row */}
                            <div
                                style={{
                                    padding: '10px 12px',
                                    borderTop: '1px solid var(--border-norm, #2d2b45)',
                                    display: 'flex',
                                    gap: 8,
                                }}
                            >
                                <textarea
                                    value={input}
                                    onChange={(e) => setInput(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                            e.preventDefault();
                                            void send();
                                        }
                                    }}
                                    placeholder="Ask about your files… (Shift+Enter for newline)"
                                    rows={2}
                                    style={{
                                        flex: 1,
                                        resize: 'none',
                                        padding: '7px 10px',
                                        background: 'var(--field-background, #2a2840)',
                                        border: '1px solid var(--field-border, #3d3a5c)',
                                        borderRadius: 6,
                                        color: 'var(--field-norm, #e2e0ff)',
                                        fontSize: 13,
                                        fontFamily: 'inherit',
                                        outline: 'none',
                                    }}
                                />
                                <button
                                    onClick={() => void send()}
                                    disabled={loading || !input.trim()}
                                    style={{
                                        background: loading || !input.trim() ? '#444' : '#6d4aff',
                                        color: '#fff',
                                        border: 'none',
                                        borderRadius: 6,
                                        padding: '0 14px',
                                        cursor: loading || !input.trim() ? 'default' : 'pointer',
                                        fontSize: 18,
                                        alignSelf: 'stretch',
                                    }}
                                    title="Send (Enter)"
                                >
                                    ↑
                                </button>
                            </div>
                        </>
                    )}

                    {keyConfigured === null && (
                        <div style={{ padding: 20, color: 'var(--text-weak, #888)', textAlign: 'center' }}>
                            Loading…
                        </div>
                    )}

                    {/* Claude Desktop MCP */}
                    <div
                        style={{
                            padding: '12px 16px',
                            borderTop: '1px solid var(--border-norm, #2d2b45)',
                            fontSize: 11,
                            color: 'var(--text-weak, #888)',
                        }}
                    >
                        <p style={{ margin: '0 0 6px', fontWeight: 600, color: 'var(--text-norm, #ccc)' }}>
                            Claude Desktop (MCP)
                        </p>
                        <p style={{ margin: '0 0 6px' }}>
                            Add to <code>claude_desktop_config.json</code>:
                        </p>
                        <pre
                            style={{
                                margin: 0,
                                padding: '6px 8px',
                                background: 'var(--background-strong, #2a2840)',
                                borderRadius: 4,
                                overflowX: 'auto',
                                fontSize: 10,
                                color: 'var(--text-norm, #e2e0ff)',
                                lineHeight: 1.4,
                            }}
                        >{`{
  "mcpServers": {
    "proton-drive": {
      "command": "/usr/local/bin/proton-drive-mcp"
    }
  }
}`}</pre>
                    </div>
                </div>
            )}
        </>
    );
};
"""


def fail(message: str) -> None:
    raise SystemExit(f"❌ {message}")


def find_main_container() -> Path:
    if not MAIN_CONTAINER_PATH.exists():
        fail("Unable to find MainContainer.tsx in current WebClients layout")
    return MAIN_CONTAINER_PATH


def patch_main_container(path: Path) -> None:
    source = path.read_text()
    if "ProtonDriveClaudeBridge" in source:
        return  # already applied

    if "ProtonDriveLinuxSyncBridge" in source:
        # Insert import after the sync bridge import
        source = source.replace(
            "import { ProtonDriveLinuxSyncBridge } from './ProtonDriveLinuxSyncBridge';\n",
            "import { ProtonDriveLinuxSyncBridge } from './ProtonDriveLinuxSyncBridge';\n"
            "import { ProtonDriveClaudeBridge } from './ProtonDriveClaudeBridge';\n",
        )
        # Insert component after the sync bridge component
        source = source.replace(
            "                    <ProtonDriveLinuxSyncBridge />\n",
            "                    <ProtonDriveLinuxSyncBridge />\n"
            "                    <ProtonDriveClaudeBridge />\n",
        )
    else:
        # Sync bridge absent — insert alongside DriveProvider imports
        source = source.replace(
            "import { DriveProvider, useActivePing, useDriveEventManager, useSearchControl } from '../legacy/store';\n",
            "import { ProtonDriveClaudeBridge } from './ProtonDriveClaudeBridge';\n"
            "import { DriveProvider, useActivePing, useDriveEventManager, useSearchControl } from '../legacy/store';\n",
        )
        source = source.replace(
            "                <DriveProvider>\n                    <SubscriptionModalProvider app={config.APP_NAME}>",
            "                <DriveProvider>\n                    <ProtonDriveClaudeBridge />\n"
            "                    <SubscriptionModalProvider app={config.APP_NAME}>",
        )

    path.write_text(source)


def main() -> None:
    if not WEBCLIENTS_DIR.exists():
        fail("WebClients directory is missing")

    container_path = find_main_container()
    bridge_path = container_path.parent / BRIDGE_FILENAME
    bridge_path.write_text(BRIDGE_SOURCE)
    patch_main_container(container_path)
    print(f"  ✓ Installed Proton Drive Claude bridge at {bridge_path.relative_to(WEBCLIENTS_DIR)}")


if __name__ == "__main__":
    main()

/**
 * Transport factory.
 * Electron remains a real C/S client: it talks to the independently running
 * FastAPI server over HTTP. IPC remains available for future local-only APIs.
 */
import type { ITransport } from '../transport/ITransport'
import { HttpTransport } from '../transport/HttpTransport'
import { IpcTransport } from '../transport/IpcTransport'

const mode = import.meta.env.VITE_TRANSPORT ?? 'http'

export const transport: ITransport = mode === 'ipc' ? new IpcTransport() : new HttpTransport()

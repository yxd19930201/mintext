/**
 * Transport factory.
 * Set VITE_TRANSPORT=ipc in .env to switch to desktop (C/S) mode.
 * Default is "http" (B/S mode).
 */
import type { ITransport } from '../transport/ITransport'
import { HttpTransport } from '../transport/HttpTransport'
import { IpcTransport } from '../transport/IpcTransport'

const mode = import.meta.env.VITE_TRANSPORT ?? 'http'

export const transport: ITransport = mode === 'ipc' ? new IpcTransport() : new HttpTransport()

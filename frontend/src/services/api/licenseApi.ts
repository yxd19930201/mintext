import { transport } from './index'
import type { ApiResponse } from '../../types/models'

export interface LicenseStatus {
  activated: boolean
  machine_code: string
  license_id?: string | null
  issued_at?: string | null
  expires_at?: string | null
  days_remaining?: number | null
  message?: string | null
}

export const licenseApi = {
  status: () => transport.get<ApiResponse<LicenseStatus>>('/license/status'),
  activate: (licenseKey: string) =>
    transport.post<ApiResponse<LicenseStatus>>('/license/activate', { license_key: licenseKey }),
}

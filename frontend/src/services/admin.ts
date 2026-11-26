/** 管理端评测 / 指标接口；所有请求携带 X-Admin-Token。 */

import { http } from './api'
import type {
  AdminDatasetsResponse,
  AdminMetricsResponse,
  AdminReportDetailResponse,
  AdminReportListResponse,
  AdminRunDetailResponse,
  AdminRunListResponse,
  AdminRunOptions,
  AdminRunStartResponse,
} from '../types'

const TOKEN_KEY = 'lvji_admin_token'

export function getAdminToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setAdminToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function headers(token?: string): Record<string, string> {
  return { 'X-Admin-Token': token ?? getAdminToken() }
}

export async function fetchAdminDatasets(token?: string): Promise<AdminDatasetsResponse> {
  const { data } = await http.get<AdminDatasetsResponse>('/admin/datasets', {
    headers: headers(token),
  })
  return data
}

export async function fetchAdminMetrics(token?: string): Promise<AdminMetricsResponse> {
  const { data } = await http.get<AdminMetricsResponse>('/admin/metrics', {
    headers: headers(token),
  })
  return data
}

export async function startAdminEval(
  options: AdminRunOptions,
  token?: string,
): Promise<AdminRunStartResponse> {
  const { data } = await http.post<AdminRunStartResponse>('/admin/eval/runs', options, {
    headers: headers(token),
  })
  return data
}

export async function fetchAdminRun(
  runId: string,
  token?: string,
): Promise<AdminRunDetailResponse> {
  const { data } = await http.get<AdminRunDetailResponse>(
    `/admin/eval/runs/${encodeURIComponent(runId)}`,
    { headers: headers(token) },
  )
  return data
}

export async function fetchAdminRuns(token?: string): Promise<AdminRunListResponse> {
  const { data } = await http.get<AdminRunListResponse>('/admin/eval/runs', {
    headers: headers(token),
  })
  return data
}

export async function cancelAdminRun(
  runId: string,
  token?: string,
): Promise<AdminRunStartResponse> {
  const { data } = await http.post<AdminRunStartResponse>(
    `/admin/eval/runs/${encodeURIComponent(runId)}/cancel`,
    {},
    { headers: headers(token) },
  )
  return data
}

export async function fetchAdminReports(token?: string): Promise<AdminReportListResponse> {
  const { data } = await http.get<AdminReportListResponse>('/admin/eval/reports', {
    headers: headers(token),
  })
  return data
}

export async function fetchAdminReport(
  name: string,
  token?: string,
): Promise<AdminReportDetailResponse> {
  const { data } = await http.get<AdminReportDetailResponse>(
    `/admin/eval/reports/${encodeURIComponent(name)}`,
    { headers: headers(token) },
  )
  return data
}

/** 把 axios 错误转成可展示的中文信息。 */
export function adminErrorText(error: unknown): string {
  const err = error as { response?: { data?: { message?: string } }; message?: string }
  return err?.response?.data?.message || err?.message || '请求失败'
}

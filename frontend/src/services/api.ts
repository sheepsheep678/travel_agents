import axios from 'axios'
import type { TripRequest, TripPlanResponse } from '../types'

const http = axios.create({
  baseURL: '/api',
  // Agent 真实调用可能长达 5 分钟，超时宁长勿短
  timeout: 600000,
})

/** 生成旅行计划（后端唯一暴露的 Agent 能力） */
export async function generateTripPlan(req: TripRequest, signal?: AbortSignal): Promise<TripPlanResponse> {
  const { data } = await http.post<TripPlanResponse>('/trip/plan', req, { signal })
  return data
}

import { reactive } from 'vue'
import type { TripPlan } from './types'

/** 跨页面共享的轻量状态（Home 生成后写入，Result 读取展示） */
export const tripStore = reactive<{
  plan: TripPlan | null
  loading: boolean
}>({
  plan: null,
  loading: false,
})

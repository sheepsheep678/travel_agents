/** 手账选城的 11 个城市 —— 与后端本地知识库（RAG 攻略）一一对应 */
export interface SketchbookCity {
  name: string
  slug: string
  en: string
}

export const sketchbookCities: SketchbookCity[] = [
  { name: '北京', slug: 'beijing', en: 'Beijing' },
  { name: '上海', slug: 'shanghai', en: 'Shanghai' },
  { name: '广州', slug: 'guangzhou', en: 'Guangzhou' },
  { name: '杭州', slug: 'hangzhou', en: 'Hangzhou' },
  { name: '西安', slug: 'xian', en: "Xi'an" },
  { name: '成都', slug: 'chengdu', en: 'Chengdu' },
  { name: '重庆', slug: 'chongqing', en: 'Chongqing' },
  { name: '长沙', slug: 'changsha', en: 'Changsha' },
  { name: '青岛', slug: 'qingdao', en: 'Qingdao' },
  { name: '厦门', slug: 'xiamen', en: 'Xiamen' },
  { name: '南京', slug: 'nanjing', en: 'Nanjing' },
]

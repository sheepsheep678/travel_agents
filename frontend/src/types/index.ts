/** 与后端 Pydantic 模型一一对应的 TypeScript 类型 */

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string | null
  rating?: number | null
  photos?: string[]
  poi_id?: string
  image_url?: string | null
  ticket_price?: number
}

export interface Meal {
  type: string
  name: string
  address?: string | null
  location?: Location | null
  description?: string | null
  estimated_cost?: number
}

export interface Hotel {
  name: string
  address?: string
  location?: Location | null
  price_range?: string
  rating?: string
  distance?: string
  type?: string
  estimated_cost?: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel | null
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather?: string
  night_weather?: string
  day_temp?: number | string
  night_temp?: number | string
  wind_direction?: string
  wind_power?: string
}

export interface Budget {
  total_attractions?: number
  total_hotels?: number
  total_meals?: number
  total_transportation?: number
  total?: number
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget | null
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan | null
}

export interface TripRequest {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}

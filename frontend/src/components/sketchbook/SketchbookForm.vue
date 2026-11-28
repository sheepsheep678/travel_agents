<template>
  <a-form layout="vertical" class="sb-form">
    <div class="sb-city">
      <span class="sb-city-label">正在翻开 · 目的地</span>
      <span class="sb-city-name">{{ city }}</span>
    </div>

    <a-form-item label="旅行日期" name="dates">
      <a-range-picker v-model:value="dates" format="YYYY-MM-DD" :allow-clear="false" style="width: 100%" />
    </a-form-item>

    <a-form-item label="出发城市（选填，用于查询跨城高铁）" name="originCity">
      <a-auto-complete
        v-model:value="originCity"
        :options="originOptions"
        placeholder="如：北京；留空则不查车次"
        style="width: 100%"
      />
    </a-form-item>

    <div class="sb-grid">
      <a-form-item label="旅行天数" name="travelDays">
        <a-input-number v-model:value="travelDays" :min="1" :max="30" style="width: 100%" />
      </a-form-item>
      <a-form-item label="交通方式" name="transportation">
        <a-auto-complete
          v-model:value="transportation"
          :options="transportationOptions"
          placeholder="下拉或自定义"
          style="width: 100%"
        />
      </a-form-item>
    </div>

    <a-form-item label="住宿偏好" name="accommodation">
      <a-auto-complete
        v-model:value="accommodation"
        :options="accommodationOptions"
        placeholder="下拉或自定义"
        style="width: 100%"
      />
    </a-form-item>

    <a-form-item label="旅行偏好" name="preferences">
      <a-select
        v-model:value="preferences"
        mode="tags"
        placeholder="选择或输入，如：自然风光、美食…"
        :max-tag-count="4"
        style="width: 100%"
      >
        <a-select-option v-for="p in preferenceOptions" :key="p" :value="p">{{ p }}</a-select-option>
      </a-select>
    </a-form-item>

    <a-form-item label="额外要求" name="freeTextInput" class="sb-notes">
      <a-textarea
        v-model:value="freeTextInput"
        :rows="2"
        placeholder="例如：希望氛围浪漫轻松、节奏慢一些…"
      />
    </a-form-item>

    <a-button type="primary" block class="sb-submit" @click="onSubmit">
      <template #icon><span>✎</span></template>
      开始规划这段旅程
    </a-button>
  </a-form>
</template>

<script setup lang="ts">
import type { Dayjs } from 'dayjs'

defineProps<{ city: string }>()
const emit = defineEmits<{ submit: [] }>()

const dates = defineModel<[Dayjs, Dayjs] | null>('dates', { required: true })
const originCity = defineModel<string>('originCity', { default: '' })
const travelDays = defineModel<number>('travelDays', { required: true })
const transportation = defineModel<string>('transportation', { required: true })
const accommodation = defineModel<string>('accommodation', { required: true })
const preferences = defineModel<string[]>('preferences', { required: true })
const freeTextInput = defineModel<string>('freeTextInput', { required: true })

const transportationOptions = ['公共交通', '自驾', '包车', '骑行', '高铁', '飞机'].map((v) => ({ value: v }))
const originOptions = ['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '西安', '南京', '重庆'].map(
  (v) => ({ value: v }),
)
const accommodationOptions = ['经济型酒店', '舒适型酒店', '豪华酒店', '民宿', '青年旅舍'].map((v) => ({ value: v }))
const preferenceOptions = [
  '历史文化', '自然风光', '美食', '休闲度假', '亲子', '购物', '夜生活',
  '博物馆', '海滩', '主题公园', '摄影', '户外徒步', '古镇', '温泉',
]

function onSubmit() {
  emit('submit')
}
</script>

<style scoped>
.sb-form :deep(.ant-form-item) {
  margin-bottom: 8px;
}
.sb-form :deep(.ant-form-item-label) {
  padding-bottom: 2px;
  line-height: 1.3;
}
.sb-form :deep(.ant-form-item-label > label) {
  font-family: var(--display);
  font-weight: 500;
  color: var(--ink-soft);
  font-size: 12px;
  line-height: 1.3;
  letter-spacing: 0.01em;
}
.sb-form :deep(.ant-form-item-label > label::after) {
  display: none;
}

/* Material 填充式输入：浅灰底 + 圆角，聚焦时白底蓝描边 */
.sb-form :deep(.ant-input),
.sb-form :deep(.ant-input-affix-wrapper),
.sb-form :deep(.ant-select-selector),
.sb-form :deep(.ant-picker),
.sb-form :deep(.ant-input-number) {
  background: var(--surface-2) !important;
  border: 1px solid transparent !important;
  border-radius: 10px !important;
  box-shadow: none !important;
  color: var(--ink);
  font-family: var(--font);
  transition: background 0.18s, border-color 0.18s, box-shadow 0.18s;
}
.sb-form :deep(.ant-input-number-input) {
  color: var(--ink);
  font-family: var(--font);
}
.sb-form :deep(.ant-input:focus),
.sb-form :deep(.ant-input-focused),
.sb-form :deep(.ant-picker-focused),
.sb-form :deep(.ant-select-focused .ant-select-selector),
.sb-form :deep(.ant-input-number-focused) {
  background: #ffffff !important;
  border-color: var(--earth) !important;
  box-shadow: 0 0 0 3px var(--blue-50) !important;
}
.sb-form :deep(.ant-input::placeholder),
.sb-form :deep(.ant-select-selection-placeholder) {
  color: var(--ink-faint);
}
.sb-form :deep(.ant-picker-input > input) {
  color: var(--ink);
  font-family: var(--font);
}
.sb-form :deep(.ant-select-selection-item) {
  color: var(--ink);
}
.sb-form :deep(.ant-select-tag) {
  background: #ffffff;
  border: 1px solid var(--blue-100);
  border-radius: 999px;
  color: var(--blue-dark);
}
.sb-form :deep(.ant-picker-suffix),
.sb-form :deep(.ant-select-arrow) {
  color: var(--ink-faint);
}
.sb-form :deep(.ant-input-number-handler-wrap) {
  opacity: 0.4;
  border-radius: 0 10px 10px 0;
}

/* 额外要求：多行备注 */
.sb-notes :deep(.ant-input) {
  padding: 7px 10px;
  line-height: 1.6;
}

/* 城市抬头 */
.sb-city {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--hairline);
}
.sb-city-label {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: var(--track-caps);
  color: var(--ink-faint);
  text-transform: uppercase;
}
.sb-city-name {
  font-family: var(--display);
  font-weight: 500;
  font-size: 27px;
  color: var(--ink);
  letter-spacing: 0.01em;
}

.sb-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.sb-grid :deep(.ant-form-item) {
  min-width: 0;
}

.sb-submit {
  margin-top: 4px;
  height: 44px;
  border-radius: 999px;
  font-size: 14.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
}
.sb-form :deep(.ant-btn-primary) {
  background: var(--earth);
  border: none;
  color: #ffffff;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.18);
  font-family: var(--font);
}
.sb-form :deep(.ant-btn-primary:hover) {
  background: var(--blue-dark);
  color: #fff;
  opacity: 1;
}

@media (max-width: 560px) {
  .sb-grid {
    grid-template-columns: 1fr;
  }
}

/* 矮屏（如 1366×768）进一步压缩纵向间距，保证表单完整落在书页内 */
@media (max-height: 820px) {
  .sb-form :deep(.ant-form-item) {
    margin-bottom: 6px;
  }
  .sb-city {
    margin-bottom: 8px;
    padding-bottom: 6px;
  }
  .sb-city-name {
    font-size: 24px;
  }
  .sb-notes :deep(.ant-input) {
    padding: 6px 10px;
  }
  .sb-submit {
    height: 42px;
    margin-top: 2px;
  }
}
</style>

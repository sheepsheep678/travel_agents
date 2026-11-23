<template>
  <div class="md-body" v-html="html"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt, { type RendererRule } from 'markdown-it'

const props = defineProps<{ content: string }>()

/**
 * 对话回复由大模型按 Markdown 输出（见 backend/app/modules/chat/workflow/prompts.py）。
 * html: false —— 不解析原始 HTML，避免注入；breaks: true —— 中文回复常用单换行断句。
 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

// 外链在新标签页打开
const defaultLinkOpen: RendererRule =
  md.renderer.rules.link_open ??
  ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// 表格过宽时横向滚动，而不是撑破消息区
md.renderer.rules.table_open = () => '<div class="md-table-wrap"><table>'
md.renderer.rules.table_close = () => '</table></div>'

const html = computed(() => md.render(props.content || ''))
</script>

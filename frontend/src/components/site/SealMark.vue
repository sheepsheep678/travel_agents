<template>
  <span class="seal" :class="`seal-${size}`" aria-hidden="true">旅</span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: 'xs' | 'sm' | 'md' | 'lg' }>(), { size: 'sm' })
</script>

/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface ImportMetaEnv {
  readonly VITE_AMAP_WEB_JS_KEY: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

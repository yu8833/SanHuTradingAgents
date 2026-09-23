<template>
  <el-select
    :model-value="modelValue"
    filterable
    remote
    clearable
    :remote-method="doSearch"
    :loading="loading"
    :disabled="disabled"
    :placeholder="placeholder"
    style="width: 100%"
    @update:model-value="onUpdate"
    @change="onChange"
    @clear="onClear"
  >
    <el-option
      v-for="s in results"
      :key="`${s.market}-${s.code}`"
      :value="s.code"
      :label="`${s.code} ${s.name}`"
    >
      <span class="sca-code">{{ s.code }}</span>
      <span class="sca-name">{{ s.name }}</span>
      <span v-if="s.name_en" class="sca-name-en">{{ s.name_en }}</span>
      <span class="sca-meta">
        <el-tag size="small" :type="marketTagType(s.market)">{{ marketLabel(s.market) }}</el-tag>
        <el-tag v-if="s.industry" size="small">{{ s.industry }}</el-tag>
      </span>
    </el-option>
    <el-option v-if="searched && !loading && !results.length" disabled value="">
      <span class="sca-empty">未找到匹配股票，可直接输入后回车/失焦确认</span>
    </el-option>
  </el-select>
</template>

<script setup lang="ts">
/**
 * 股票「代码/名称」联想输入（多市场）。
 *
 * 在同一个输入框里输入**股票代码或股票名称**（如 600519 / 贵州茅台），
 * 防抖远程匹配后弹出「代码 + 名称」候选项；选中后通过 v-model 输出股票代码，
 * 并通过 select 事件输出完整 StockInfo（父组件据此自动回填股票名称等字段）。
 *
 * 用法：
 *   <StockCodeAutocomplete v-model="form.symbol" :markets="['CN']" @select="onPick" />
 */
import { ref } from 'vue'
import { searchStocks, type StockInfo } from '@/api/multiMarket'

interface Props {
  modelValue?: string
  placeholder?: string
  /** 搜索的市场，默认仅 A 股；多市场传 ['CN','HK','US'] */
  markets?: string[]
  disabled?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  placeholder: '输入股票代码或名称（如 600519 或 贵州茅台）',
  markets: () => ['CN'],
  disabled: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'select', stock: StockInfo): void
  (e: 'clear'): void
}>()

const loading = ref(false)
const searched = ref(false)
const results = ref<StockInfo[]>([])
let timer: ReturnType<typeof setTimeout> | null = null

const marketLabel = (m: string) => ({ CN: 'A股', HK: '港股', US: '美股' }[m] || m)
const marketTagType = (m: string) => (m === 'CN' ? 'success' : m === 'HK' ? 'warning' : 'info')

const doSearch = (query: string) => {
  if (timer) clearTimeout(timer)
  const q = (query || '').trim()
  if (!q) {
    results.value = []
    searched.value = false
    return
  }
  timer = setTimeout(async () => {
    loading.value = true
    try {
      const settled = await Promise.allSettled(
        props.markets.map((m) => searchStocks(m, q, 10))
      )
      const seen = new Set<string>()
      const merged: StockInfo[] = []
      for (const r of settled) {
        if (r.status !== 'fulfilled' || !r.value?.data?.stocks) continue
        for (const s of r.value.data.stocks) {
          const key = `${s.market}-${s.code}`
          if (!seen.has(key)) {
            seen.add(key)
            merged.push(s)
          }
        }
      }
      results.value = merged
      searched.value = true
    } catch (e) {
      console.error('股票联想搜索失败', e)
      results.value = []
      searched.value = true
    } finally {
      loading.value = false
    }
  }, 300)
}

const onUpdate = (v: any) => {
  emit('update:modelValue', (v ?? '') as string)
}

const onChange = (v: any) => {
  const code = (v ?? '') as string
  if (!code) return
  const picked = results.value.find((s) => s.code === code)
  if (picked) {
    emit('update:modelValue', code)
    emit('select', picked)
  }
}

const onClear = () => {
  emit('update:modelValue', '')
  emit('clear')
}
</script>

<style scoped lang="scss">
.sca-code {
  font-family: var(--app-font-mono, 'SFMono-Regular', ui-monospace, Menlo, monospace);
  font-weight: 600;
  margin-right: 8px;
}
.sca-name {
  margin-right: 6px;
}
.sca-name-en {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 8px;
}
.sca-meta {
  float: right;
}
.sca-empty {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
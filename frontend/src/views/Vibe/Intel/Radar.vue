<template>
  <div class="radar-page">
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><DataLine /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">资讯</h2>
          <p class="page-hero-sub">12赛道全球公开RSS资讯</p>
        </div>
      </div>
    </div>

    <div class="status-bar">
      <div class="status-info">
        <span class="status-num">{{ stats.total_sources || '--' }}</span> 个公开源
        <span class="status-sep">·</span>
        近 <span class="status-num">{{ radarData?.recent_days ?? '-' }}</span> 天
        <span class="status-sep">·</span>
        更新于 <span class="status-time">{{ radarData?.generated_at || '-' }}</span>
      </div>
      <div class="status-actions">
        <el-button :loading="refreshing" :disabled="refreshing" @click="refresh">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <div v-if="!radarData && !loadingError" class="skeleton-wrap">
      <div class="skeleton-pills">
        <div v-for="i in 6" :key="i" class="skeleton-pill"></div>
      </div>
      <div class="skeleton-tabs">
        <div class="skeleton-tab-header"></div>
        <div class="skeleton-summary"></div>
        <div class="skeleton-list">
          <div class="skeleton-list-header"></div>
          <div v-for="i in 8" :key="i" class="skeleton-item"></div>
        </div>
      </div>
    </div>

    <div v-else-if="loadingError" class="error-state">
      <el-empty description="资讯加载失败，请点击刷新重试" :image-size="80">
        <el-button type="primary" @click="loadRadar">
          <el-icon><Refresh /></el-icon>
          重新加载
        </el-button>
      </el-empty>
    </div>

    <template v-else>
      <div class="industry-pills">
        <button
          v-for="ind in industries"
          :key="ind.key"
          class="pill"
          :class="{ active: ind.key === currentKey }"
          @click="switchIndustry(ind.key)"
        >
          <span class="dot" :style="{ background: ind.accent }"></span>
          <span class="pill-name">{{ ind.name }}</span>
          <span class="pill-count">{{ ind.total }}</span>
        </button>
      </div>

      <el-tabs v-model="activeTab" class="main-tabs">
        <el-tab-pane label="资讯" name="news">
          <div class="summary-box">
            <div class="summary-head">
              <div class="summary-title">
                <el-icon><MagicStick /></el-icon>
                今日要点<span v-if="currentIndustry"> · {{ currentIndustry.name }}</span>
              </div>
              <div class="summary-actions" v-if="summaryState === 'done'">
                <el-button size="small" type="primary" plain @click="saveSummary">
                  <el-icon><EditPen /></el-icon>
                  存入沉淀
                </el-button>
                <el-button size="small" link @click="resetSummary">重新提炼</el-button>
              </div>
            </div>
            <div class="summary-body">
              <div v-if="summaryState === 'idle'" class="summary-idle">
                <el-button type="warning" @click="distillCurrent">
                  <el-icon><MagicStick /></el-icon>
                  让 AI 提炼今日要点
                </el-button>
              </div>
              <div
                v-else-if="summaryState === 'loading' || summaryState === 'done'"
                class="summary-text"
                :class="{ streaming: summaryState === 'loading' }"
              >
                {{ currentSummary || '...' }}
                <span v-if="summaryState === 'loading'" class="cursor">▌</span>
              </div>
              <div v-if="summaryError" class="summary-error">
                <el-icon><Warning /></el-icon>
                {{ summaryError }}
              </div>
            </div>
          </div>

          <div class="news-list">
            <div class="list-head">
              <el-icon><Reading /></el-icon>
              <span>资讯列表</span>
              <span class="list-count">共 {{ currentItems.length }} 条</span>
            </div>
            <div v-if="currentItems.length === 0" class="empty">
              <el-empty description="该板块暂无资讯" />
            </div>
            <a
              v-for="(item, idx) in currentItems"
              :key="idx"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
              class="news-item"
            >
              <span class="news-time">{{ item.time }}</span>
              <span class="news-source">{{ item.source }}</span>
              <span class="news-title">{{ item.title }}</span>
            </a>
          </div>
        </el-tab-pane>

        <el-tab-pane label="分析" name="analysis">
          <div class="analysis-content">
            <template v-if="sectorsLoading">
              <div class="analysis-skeleton">
                <div class="as-header"></div>
                <div class="as-summary"></div>
                <div class="as-section"></div>
                <div class="as-section"></div>
                <div class="as-section"></div>
              </div>
            </template>
            <template v-else-if="currentSector">
              <div class="page-header">
                <h1 class="page-title" style="font-size: 22px;">{{ currentSector.label }}</h1>
                <p class="page-tagline">{{ currentSector.tagline || '—' }}</p>
              </div>

              <div v-if="currentSector.summary" class="summary-card">
                <div class="summary-label">核心矛盾</div>
                <div class="summary-text">{{ currentSector.summary }}</div>
              </div>

              <template v-if="hasLayers">
                <div class="section-title">
                  <span>产业链结构</span>
                  <span class="section-sub">自上而下三层</span>
                </div>
                <div class="layers-wrap">
                  <div v-for="(layer, idx) in currentSector.layers" :key="layer.name" class="layer-block">
                    <div class="layer-header">
                      <span class="layer-index">{{ idx + 1 }}</span>
                      <div class="layer-titles">
                        <div class="layer-name">{{ layer.name }}</div>
                        <div class="layer-desc">{{ layer.desc }}</div>
                      </div>
                    </div>
                    <div class="layer-grid">
                      <div v-for="n in layer.nodes" :key="n.name" class="link-card">
                        <div class="link-head">
                          <span class="link-name">{{ n.name }}</span>
                          <span class="bottleneck-dot" :class="`bn-${n.bottleneck}`" :title="bottleneckText(n.bottleneck)"></span>
                        </div>
                        <div class="link-role">{{ n.role }}</div>
                        <div class="link-focus">
                          <span class="focus-label">焦点</span>
                          <span class="focus-text">{{ n.focus }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>

              <template v-if="hasLinks">
                <div class="section-title">
                  <span>关键环节</span>
                  <span class="section-sub">环节 / 核心作用 / 当前产业焦点 / 卡脖子等级</span>
                </div>
                <el-table :data="flatLinks" class="app-table app-table--compact" stripe>
                  <el-table-column prop="layer" label="所属层" width="140" />
                  <el-table-column prop="name" label="环节" width="120" />
                  <el-table-column prop="role" label="核心作用" min-width="200" />
                  <el-table-column prop="focus" label="当前产业焦点" min-width="240" />
                  <el-table-column label="卡脖子" width="100" align="center">
                    <template #default="{ row }">
                      <span class="bn-pill" :class="`bn-${row.bottleneck}`">
                        {{ bottleneckText(row.bottleneck) }}
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </template>

              <template v-if="hasBottlenecks">
                <div class="section-title">
                  <span>卡脖子点分析</span>
                  <span class="section-sub">制造与设备 / 生态与设计 / 关键部件与材料</span>
                </div>
                <div class="bn-grid">
                  <div v-for="b in currentSector.bottlenecks" :key="b.dimension" class="bn-card">
                    <div class="bn-card-head">
                      <el-icon class="bn-card-icon"><Warning /></el-icon>
                      <span class="bn-card-title">{{ b.dimension }}</span>
                    </div>
                    <ul class="bn-list">
                      <li v-for="(it, i) in b.items" :key="i">{{ it }}</li>
                    </ul>
                  </div>
                </div>
              </template>

              <template v-if="currentSector.verified && !hasLayers && !hasLinks">
                <div class="section-title">核心环节</div>
                <div class="nodes-cloud">
                  <el-tag
                    v-for="node in currentSector.nodes"
                    :key="node"
                    class="node-pill"
                    effect="plain"
                    round
                  >
                    {{ node }}
                  </el-tag>
                  <span v-if="!currentSector.nodes.length" class="nodes-empty">暂无环节</span>
                </div>
              </template>

              <el-alert
                v-if="!currentSector.verified"
                class="pending-alert"
                type="info"
                :closable="false"
                show-icon
              >
                环节骨架尚在实时核实补全中
              </el-alert>

              <div class="ai-section">
                <div class="section-title">
                  <span>AI 深度拆解</span>
                  <span class="section-sub">基于上方结构化骨架，由 LLM 补充：近期事件 / 国内代表企业 / 核心矛盾解读</span>
                </div>
                <div class="action-bar">
                  <el-button
                    type="primary"
                    :loading="aiLoading"
                    :disabled="aiLoading"
                    @click="runAiAnalysis"
                  >
                    <el-icon v-if="!aiLoading"><MagicStick /></el-icon>
                    {{ aiResult ? '重新生成' : '让 AI 深度拆解' }}
                  </el-button>
                  <el-button
                    v-if="aiResult && !aiLoading"
                    type="success"
                    plain
                    @click="saveToNotes"
                  >
                    <el-icon><Plus /></el-icon>
                    存入沉淀
                  </el-button>
                </div>
                <el-card v-if="aiResult || aiLoading" class="ai-output-card" shadow="never">
                  <div v-if="aiLoading && !aiResult" class="ai-streaming">
                    <span class="stream-cursor">AI 正在深度拆解</span>
                    <span class="dots">...</span>
                  </div>
                  <div
                    v-else
                    class="ai-output"
                    v-html="renderedAi"
                  ></div>
                </el-card>
              </div>
            </template>

            <el-empty
              v-else
              description="该板块分析内容正在建设中，敬请期待"
            >
              <template #image>
                <el-icon :size="80" color="#c0c4cc"><Reading /></el-icon>
              </template>
            </el-empty>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataLine,
  Refresh,
  MagicStick,
  Reading,
  EditPen,
  Warning,
  Plus
} from '@element-plus/icons-vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import { vibeApi } from '@/api/vibe'
import type { RadarData, Industry, RadarItem, SectorNode, SectorLink, BottleneckLevel } from '@/api/vibe'

marked.setOptions({ breaks: true, gfm: true })

const INDUSTRY_TO_SECTOR_MAP: Record<string, string> = {
  'ai': 'ai-computing',
  'robot': 'humanoid',
}

const loading = ref(false)
const loadingError = ref(false)
const refreshing = ref(false)
const radarData = ref<RadarData | null>(null)
const activeTab = ref('news')

const currentKey = ref('')
const industries = computed<Industry[]>(() => radarData.value?.industries ?? [])
const stats = computed(() => radarData.value?.stats ?? { industries: 0, total_sources: 0 })

const currentIndustry = computed<Industry | undefined>(() =>
  industries.value.find(i => i.key === currentKey.value)
)

const currentItems = ref<RadarItem[]>([])

watch([currentKey, radarData], ([key]) => {
  const industry = industries.value.find(i => i.key === key)
  if (!industry) {
    currentItems.value = []
    return
  }
  currentItems.value = [...industry.items].sort((a, b) => {
    const ta = a.ts ?? new Date(a.time).getTime()
    const tb = b.ts ?? new Date(b.time).getTime()
    return (tb || 0) - (ta || 0)
  })
}, { immediate: true })

type SummaryState = 'idle' | 'loading' | 'done'
const summaryState = ref<SummaryState>('idle')
const currentSummary = ref('')
const summaryError = ref('')
const summaryCache = ref<Record<string, string>>({})

const sortByTime = (items: RadarItem[]): RadarItem[] =>
  [...items].sort((a, b) => {
    const ta = a.ts ?? new Date(a.time).getTime()
    const tb = b.ts ?? new Date(b.time).getTime()
    return (tb || 0) - (ta || 0)
  })

const buildPrompt = (ind: Industry): string => {
  const list = sortByTime(ind.items)
    .slice(0, 20)
    .map(it => `- [${it.time}] ${it.title} (${it.source})`)
    .join('\n')
  return `以下是「${ind.name}」板块近期资讯。请提炼「今日要点」3-5 条：每条一句话（≤40 字），只客观陈述重要事件/趋势，不推荐标的、不预测涨跌、不构成建议。直接用「- 」列点。\n\n资讯列表：\n${list}`
}

const distillCurrent = async () => {
  const ind = currentIndustry.value
  if (!ind || ind.items.length === 0) {
    ElMessage.warning('当前板块暂无资讯')
    return
  }
  summaryState.value = 'loading'
  currentSummary.value = ''
  summaryError.value = ''
  try {
    await vibeApi.chatStream(
      [{ role: 'user', content: buildPrompt(ind) }],
      'radar',
      (delta) => { currentSummary.value += delta },
      (msg) => { summaryError.value = msg }
    )
    summaryCache.value[ind.key] = currentSummary.value
    summaryState.value = 'done'
  } catch (e: any) {
    summaryError.value = e?.message || '提炼失败'
    summaryState.value = 'idle'
  }
}

const resetSummary = () => {
  summaryState.value = 'idle'
  currentSummary.value = ''
  summaryError.value = ''
}

const saveSummary = async () => {
  const ind = currentIndustry.value
  if (!ind || !currentSummary.value) return
  try {
    await vibeApi.saveNote('今日要点', `板块资讯·${ind.name}·今日要点`, currentSummary.value)
    ElMessage.success('已存入研究记录')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  }
}

const switchIndustry = (key: string) => {
  currentKey.value = key
}

watch(currentKey, (key) => {
  if (summaryCache.value[key]) {
    currentSummary.value = summaryCache.value[key]
    summaryState.value = 'done'
  } else {
    currentSummary.value = ''
    summaryState.value = 'idle'
  }
  summaryError.value = ''
})

const sectorsLoading = ref(false)
const sectors = ref<SectorNode[]>([])

const currentSector = computed<SectorNode | null>(() => {
  const sectorKey = INDUSTRY_TO_SECTOR_MAP[currentKey.value]
  if (!sectorKey) return null
  return sectors.value.find(s => s.key === sectorKey) || null
})

const hasLayers = computed(() => Array.isArray(currentSector.value?.layers) && currentSector.value!.layers!.length > 0)
const hasLinks = computed(() => hasLayers.value && currentSector.value!.layers!.some(l => l.nodes?.length))
const hasBottlenecks = computed(() => Array.isArray(currentSector.value?.bottlenecks) && currentSector.value!.bottlenecks!.length > 0)

const flatLinks = computed(() => {
  if (!currentSector.value?.layers) return []
  const rows: (SectorLink & { layer: string })[] = []
  for (const layer of currentSector.value.layers) {
    for (const n of (layer.nodes || [])) {
      rows.push({ ...n, layer: layer.name })
    }
  }
  return rows
})

const bottleneckText = (lv: BottleneckLevel) => {
  if (lv === 'high') return '深水区'
  if (lv === 'mid') return '中度'
  return '可控'
}

const aiLoading = ref(false)
const aiResult = ref('')

const renderedAi = computed(() => {
  if (!aiResult.value) return ''
  try {
    return sanitizeHtml(String(marked.parse(aiResult.value)))
  } catch {
    return sanitizeHtml(aiResult.value.replace(/\n/g, '<br/>'))
  }
})

const buildAiPrompt = (s: SectorNode) => {
  const lines: string[] = []
  lines.push(`板块：${s.label}`)
  lines.push(`定位：${s.tagline || '—'}`)
  if (s.summary) lines.push(`核心矛盾：${s.summary}`)

  if (s.layers?.length) {
    lines.push('\n# 已梳理的产业链分层骨架（请基于此深化，不要重新列举）：')
    s.layers.forEach((l, i) => {
      lines.push(`\n## ${i + 1}. ${l.name}（${l.desc}）`)
      l.nodes.forEach(n => {
        lines.push(`- ${n.name}：核心作用=${n.role}；当前焦点=${n.focus}；卡脖子等级=${bottleneckText(n.bottleneck)}`)
      })
    })
  } else {
    lines.push(`\n产业链环节：${(s.nodes || []).join('、') || '（环节梳理中）'}`)
  }

  if (s.bottlenecks?.length) {
    lines.push('\n# 已梳理的卡脖子维度（请基于此深化）：')
    s.bottlenecks.forEach(b => {
      lines.push(`- ${b.dimension}：${b.items.join('；')}`)
    })
  }

  lines.push('\n# 请按以下 Markdown 骨架输出（标题必须严格使用以下三个二级标题）：')
  lines.push('\n## 一、近期技术进展与标志性事件')
  lines.push('按产业链环节分小节（用三级标题 `###`），每个环节列出 1-2 条近期进展或事件。')
  lines.push('\n## 二、国内代表企业（仅作环节映射）')
  lines.push('按产业链环节分小节（用三级标题 `###`），每个环节列出 1-2 家国内代表企业，仅用于环节定位，不构成推荐。')
  lines.push('\n## 三、核心矛盾的进一步解读')
  lines.push('200-300 字，对上方"核心矛盾"做深入解读，强调产业链协同与三角地带突破逻辑。')
  lines.push('\n# 硬性规则：')
  lines.push('- 只做信息整理与多视角分析')
  lines.push('- 不推荐任何具体买卖、不预测涨跌与价位、不给买卖时机、不承诺收益')
  lines.push('- 不编造具体数字与时间，需要时使用「近期」/「2024 年以来」等模糊表述')
  lines.push('- 严格使用 Markdown 格式，标题层级清晰，便于阅读')
  return lines.join('\n')
}

const runAiAnalysis = async () => {
  if (!currentSector.value || aiLoading.value) return
  aiLoading.value = true
  aiResult.value = ''
  const prompt = buildAiPrompt(currentSector.value)
  try {
    await vibeApi.chatStream(
      [{ role: 'user', content: prompt }],
      'sector_analysis',
      (delta: string) => {
        aiResult.value += delta
      },
      (msg: string) => {
        ElMessage.error(msg || 'AI 分析出错')
      }
    )
  } catch (e: any) {
    ElMessage.error(e?.message || 'AI 分析失败')
  } finally {
    aiLoading.value = false
  }
}

const saveToNotes = async () => {
  if (!aiResult.value || !currentSector.value) return
  try {
    await vibeApi.saveNote(
      '问AI',
      `${currentSector.value.label} · AI 深度拆解`,
      aiResult.value
    )
    ElMessage.success('已存入研究记录')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  }
}

const loadSectors = async () => {
  sectorsLoading.value = true
  try {
    const res = await vibeApi.getSectors()
    sectors.value = res?.data?.sectors || []
  } catch (e: any) {
    console.error('加载板块数据失败:', e)
  } finally {
    sectorsLoading.value = false
  }
}

const loadRadar = async () => {
  loading.value = true
  loadingError.value = false
  try {
    const res = await vibeApi.getRadar()
    radarData.value = res.data
    if (!currentKey.value && industries.value.length > 0) {
      currentKey.value = industries.value[0].key
    }
  } catch (e: any) {
    loadingError.value = true
    console.error('加载资讯失败:', e)
  } finally {
    loading.value = false
  }
}

const refresh = async () => {
  refreshing.value = true
  loadingError.value = false
  try {
    const res = await vibeApi.refreshRadar()
    radarData.value = res.data
    ElMessage.success('已刷新')
  } catch (e: any) {
    ElMessage.error(e?.message || '刷新失败')
  } finally {
    refreshing.value = false
  }
}

watch(currentKey, () => {
  aiResult.value = ''
  aiLoading.value = false
})

onMounted(() => {
  loadRadar()
  loadSectors()
})
</script>

<style scoped lang="scss">
.radar-page {
  padding: 4px 8px;
  max-width: 1120px;
  margin: 0 auto;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.page-header {
  margin-bottom: 20px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0;
}

.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  margin-bottom: 18px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.status-num {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.status-sep {
  margin: 0 8px;
  color: var(--el-text-color-placeholder);
}

.status-time {
  font-family: var(--app-font-mono);
  font-size: 12px;
}

.status-actions {
  display: flex;
  gap: 8px;
}

.skeleton-wrap {
  margin-top: 4px;
}

.skeleton-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.skeleton-pill {
  width: 80px;
  height: 32px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  border-radius: 999px;
}

.skeleton-tabs {
  background: #fff;
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
  overflow: hidden;
}

.skeleton-tab-header {
  height: 48px;
  background: var(--el-fill-color-light);
  margin-bottom: 16px;
}

.skeleton-summary {
  margin: 0 16px 20px;
  padding: 16px;
  border: 1.5px solid #e8722c;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(232, 114, 44, 0.05), rgba(232, 114, 44, 0.01));

  &::before {
    content: '';
    display: block;
    height: 20px;
    width: 30%;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 4px;
    margin-bottom: 12px;
  }

  &::after {
    content: '';
    display: block;
    height: 16px;
    width: 60%;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 4px;
  }
}

.skeleton-list {
  padding: 0 16px 16px;
}

.skeleton-list-header {
  height: 40px;
  background: var(--el-fill-color-light);
  margin-bottom: 12px;
  border-radius: 4px;
}

.skeleton-item {
  height: 40px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 8px;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.error-state {
  padding: 60px 20px;
  text-align: center;
}

.industry-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
  min-height: 36px;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 999px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
}

.pill:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.pill.active {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  color: #fff;
}

.pill.active .dot {
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.55);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pill-count {
  font-size: 11px;
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 7px;
  border-radius: 10px;
  line-height: 1.6;
}

.pill.active .pill-count {
  background: rgba(255, 255, 255, 0.28);
}

.main-tabs {
  margin-top: 4px;
}

.summary-box {
  border: 1.5px solid #e8722c;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 24px;
  background: linear-gradient(135deg, rgba(232, 114, 44, 0.05), rgba(232, 114, 44, 0.01));
}

.summary-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.summary-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  color: #c75c1c;
  font-size: 15px;
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-body {
  min-height: 48px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.summary-idle {
  display: flex;
  align-items: center;
}

.summary-text {
  white-space: pre-wrap;
  line-height: 1.85;
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.summary-text.streaming {
  color: var(--el-text-color-regular);
}

.cursor {
  animation: blink 1s steps(2) infinite;
  color: #e8722c;
  font-weight: 600;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.summary-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--el-color-danger);
  font-size: 13px;
  margin-top: 8px;
}

.news-list {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
}

.list-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-light);
  font-weight: 600;
  color: var(--el-text-color-primary);
  font-size: 14px;
}

.list-count {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.empty {
  padding: 40px 0;
}

.news-item {
  display: grid;
  grid-template-columns: 150px 110px 1fr;
  gap: 16px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  text-decoration: none;
  color: var(--el-text-color-primary);
  transition: background 0.15s ease;
  align-items: baseline;
}

.news-item:hover {
  background: var(--el-fill-color-light);
}

.news-item:last-child {
  border-bottom: none;
}

.news-time {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.news-source {
  font-size: 12px;
  color: var(--el-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.news-title {
  font-size: 14px;
  line-height: 1.5;
  transition: color 0.15s ease;
}

.news-item:hover .news-title {
  color: var(--el-color-primary);
}

.analysis-content {
  min-height: 400px;
  padding-top: 8px;
}

.analysis-skeleton {
  padding: 0 16px;

  .as-header {
    height: 40px;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 4px;
    margin-bottom: 8px;
  }

  .as-summary {
    height: 80px;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 8px;
    margin-bottom: 20px;
  }

  .as-section {
    height: 120px;
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 8px;
    margin-bottom: 16px;
  }
}

.analysis-content {
  .page-header {
    margin-bottom: 20px;

    .page-title {
      font-size: 22px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 6px 0;
    }

    .page-tagline {
      font-size: 14px;
      color: var(--el-text-color-secondary);
      margin: 0;
    }
  }

  .summary-card {
    background: linear-gradient(135deg, #fff7e6 0%, #ffe7ba 100%);
    border: 1px solid #ffd591;
    border-left: 4px solid #fa8c16;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 24px;

    .summary-label {
      font-size: 12px;
      font-weight: 600;
      color: #d46b08;
      letter-spacing: 1px;
      margin-bottom: 6px;
    }

    .summary-text {
      font-size: 14px;
      line-height: 1.75;
      color: #874d00;
    }
  }

  .section-title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    font-size: 16px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin: 28px 0 12px;

    .section-sub {
      font-size: 12px;
      font-weight: 400;
      color: var(--el-text-color-placeholder);
    }
  }

  .layers-wrap {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-bottom: 8px;
  }

  .layer-block {
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 8px;
    background: #fafbfc;
    overflow: hidden;
  }

  .layer-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: linear-gradient(90deg, #f0f5ff 0%, #fafbfc 100%);
    border-bottom: 1px solid var(--el-border-color-lighter);

    .layer-index {
      flex-shrink: 0;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background: #2b6cb0;
      color: #fff;
      font-size: 13px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    .layer-name {
      font-size: 15px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .layer-desc {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      margin-top: 2px;
    }
  }

  .layer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
    padding: 14px 16px;
  }

  .link-card {
    background: #fff;
    border: 1px solid var(--el-border-color-lighter);
    border-radius: 6px;
    padding: 12px 14px;
    transition: box-shadow 0.2s, transform 0.2s;

    &:hover {
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
      transform: translateY(-1px);
    }

    .link-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }

    .link-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .bottleneck-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
    }

    .bn-high { background: #f5222d; box-shadow: 0 0 0 3px rgba(245, 34, 45, 0.12); }
    .bn-mid  { background: #fa8c16; box-shadow: 0 0 0 3px rgba(250, 140, 22, 0.12); }
    .bn-low  { background: #52c41a; box-shadow: 0 0 0 3px rgba(82, 196, 26, 0.12); }

    .link-role {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      line-height: 1.6;
      margin-bottom: 8px;
    }

    .link-focus {
      font-size: 12px;
      line-height: 1.6;
      background: #f5f7fa;
      border-radius: 4px;
      padding: 6px 8px;

      .focus-label {
        font-weight: 600;
        color: #2b6cb0;
        margin-right: 4px;
      }

      .focus-text {
        color: var(--el-text-color-regular);
      }
    }
  }

  .bn-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 500;

    &.bn-high { background: #fff1f0; color: #f5222d; border: 1px solid #ffa39e; }
    &.bn-mid  { background: #fff7e6; color: #d46b08; border: 1px solid #ffd591; }
    &.bn-low  { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }
  }

  .bn-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 14px;
  }

  .bn-card {
    border: 1px solid #ffccc7;
    border-radius: 8px;
    background: linear-gradient(180deg, #fffafa 0%, #fff 60%);
    padding: 14px 16px;

    .bn-card-head {
      display: flex;
      align-items: center;
      gap: 8px;
      padding-bottom: 10px;
      margin-bottom: 10px;
      border-bottom: 1px dashed #ffd6d4;
    }

    .bn-card-icon {
      color: #f5222d;
      font-size: 16px;
    }

    .bn-card-title {
      font-size: 14px;
      font-weight: 600;
      color: #cf1322;
    }

    .bn-list {
      margin: 0;
      padding: 0;
      list-style: none;

      li {
        position: relative;
        font-size: 13px;
        line-height: 1.7;
        color: var(--el-text-color-regular);
        padding: 6px 0 6px 14px;
        border-bottom: 1px dashed var(--el-border-color-lighter);

        &:last-child { border-bottom: none; }

        &::before {
          content: '';
          position: absolute;
          left: 0;
          top: 14px;
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: #f5222d;
          opacity: 0.6;
        }
      }
    }
  }

  .ai-section {
    margin-top: 32px;
    padding-top: 24px;
    border-top: 1px dashed var(--el-border-color-lighter);
  }

  .action-bar {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-bottom: 16px;
  }

  .ai-output-card {
    margin-bottom: 24px;
    border-radius: 8px;
    border: 1px solid #d6e4ff;
    background: linear-gradient(180deg, #f0f5ff 0%, #fff 30%);

    .ai-streaming {
      color: var(--el-text-color-secondary);
      font-size: 14px;
      padding: 8px 4px;

      .dots {
        margin-left: 2px;
      }
    }

    .ai-output {
      font-size: 14px;
      line-height: 1.8;
      color: var(--el-text-color-primary);
      word-break: break-word;

      :deep(h1) {
        font-size: 20px;
        margin: 16px 0 10px;
        padding-bottom: 6px;
        border-bottom: 2px solid #2b6cb0;
      }

      :deep(h2) {
        font-size: 17px;
        margin: 18px 0 10px;
        padding: 6px 12px;
        background: linear-gradient(90deg, #e6f0ff 0%, transparent 100%);
        border-left: 4px solid #2b6cb0;
        color: #2c5282;
        font-weight: 600;
      }

      :deep(h3) {
        font-size: 15px;
        margin: 12px 0 6px;
        color: #2b6cb0;
        font-weight: 600;
      }

      :deep(h4) {
        font-size: 14px;
        margin: 10px 0 4px;
        color: var(--el-text-color-primary);
        font-weight: 600;
      }

      :deep(p) {
        margin: 6px 0;
      }

      :deep(ul),
      :deep(ol) {
        padding-left: 22px;
        margin: 6px 0;

        li {
          margin: 3px 0;
        }
      }

      :deep(strong) {
        color: #2c5282;
      }

      :deep(blockquote) {
        margin: 10px 0;
        padding: 8px 14px;
        background: #f5f7fa;
        border-left: 4px solid #909399;
        color: var(--el-text-color-regular);
        font-size: 13px;
        border-radius: 0 4px 4px 0;
      }

      :deep(code) {
        background: var(--el-fill-color-light);
        padding: 2px 5px;
        border-radius: 3px;
        font-size: 13px;
        color: #c41d7f;
      }

      :deep(pre) {
        background: #1e1e1e;
        color: #d4d4d4;
        padding: 12px 14px;
        border-radius: 6px;
        overflow-x: auto;
        line-height: 1.6;

        code {
          background: transparent;
          color: inherit;
          padding: 0;
        }
      }
    }
  }

  .nodes-cloud {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 24px;

    .node-pill {
      border-color: #e6a23c;
      color: #b88200;
      background-color: #fdf6ec;
      font-size: 13px;
    }

    .nodes-empty {
      font-size: 13px;
      color: var(--el-text-color-placeholder);
    }
  }

  .pending-alert {
    margin-bottom: 24px;
    border-radius: 8px;
  }
}

@media (max-width: 720px) {
  .news-item {
    grid-template-columns: 1fr;
    gap: 4px;
  }
}
</style>
<template>
  <div class="sector-detail-page">
    <div class="back-link" @click="goBack">
      <el-icon><ArrowLeft /></el-icon>
      <span>全部板块</span>
    </div>

    <div v-loading="loading" class="detail-body">
      <template v-if="sector">
        <div class="page-header">
          <h1 class="page-title">{{ sector.label }}</h1>
          <p class="page-tagline">{{ sector.tagline || '—' }}</p>
        </div>

        <!-- 1. 核心矛盾 -->
        <div v-if="sector.summary" class="summary-card">
          <div class="summary-label">核心矛盾</div>
          <div class="summary-text">{{ sector.summary }}</div>
        </div>

        <!-- 2. 产业链结构（分层卡片） -->
        <template v-if="hasLayers">
          <div class="section-title">
            <span>产业链结构</span>
            <span class="section-sub">自上而下三层</span>
          </div>
          <div class="layers-wrap">
            <div v-for="(layer, idx) in sector.layers" :key="layer.name" class="layer-block">
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

        <!-- 3. 关键环节表 -->
        <template v-if="hasLinks">
          <div class="section-title">
            <span>关键环节</span>
            <span class="section-sub">环节 / 核心作用 / 当前产业焦点 / 卡脖子等级</span>
          </div>
          <el-table :data="flatLinks" class="links-table" stripe>
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

        <!-- 4. 卡脖子点分析 -->
        <template v-if="hasBottlenecks">
          <div class="section-title">
            <span>卡脖子点分析</span>
            <span class="section-sub">制造与设备 / 生态与设计 / 关键部件与材料</span>
          </div>
          <div class="bn-grid">
            <div v-for="b in sector.bottlenecks" :key="b.dimension" class="bn-card">
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

        <!-- 兼容旧版：verified=true 但仅有 nodes 无 layers 时，渲染旧版标签云 -->
        <template v-if="sector.verified && !hasLayers && !hasLinks">
          <div class="section-title">核心环节</div>
          <div class="nodes-cloud">
            <el-tag
              v-for="node in sector.nodes"
              :key="node"
              class="node-pill"
              effect="plain"
              round
            >
              {{ node }}
            </el-tag>
            <span v-if="!sector.nodes.length" class="nodes-empty">暂无环节</span>
          </div>
        </template>

        <!-- verified=false 的板块：占位 -->
        <el-alert
          v-if="!sector.verified"
          class="pending-alert"
          type="info"
          :closable="false"
          show-icon
        >
          环节骨架尚在实时核实补全中
        </el-alert>

        <!-- 5. AI 深度拆解（放在最下方，作为补充动态内容） -->
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
        v-else-if="!loading"
        description="未找到该板块"
      />
    </div>

    <p class="disclaimer">
      只有环节，不含标的。用户可在本地挂自己的标的。
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, MagicStick, Plus, Warning } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { vibeApi } from '@/api/vibe'
import type { SectorNode, SectorLink, BottleneckLevel } from '@/api/vibe'

marked.setOptions({ breaks: true, gfm: true })

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const aiLoading = ref(false)
const sector = ref<SectorNode | null>(null)
const aiResult = ref('')

const renderedAi = computed(() => {
  if (!aiResult.value) return ''
  try {
    return String(marked.parse(aiResult.value))
  } catch {
    return aiResult.value.replace(/\n/g, '<br/>')
  }
})

const sectorKey = computed(() => String(route.params.key || ''))

// 是否有结构化数据
const hasLayers = computed(() => Array.isArray(sector.value?.layers) && sector.value!.layers!.length > 0)
const hasLinks = computed(() => hasLayers.value && sector.value!.layers!.some(l => l.nodes?.length))
const hasBottlenecks = computed(() => Array.isArray(sector.value?.bottlenecks) && sector.value!.bottlenecks!.length > 0)

// 表格用：扁平化所有环节 + 标注所属层
const flatLinks = computed(() => {
  if (!sector.value?.layers) return []
  const rows: (SectorLink & { layer: string })[] = []
  for (const layer of sector.value.layers) {
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

const bottleneckLabelMap: Record<BottleneckLevel, string> = {
  high: '深水区（高度依赖）',
  mid: '中度（部分依赖）',
  low: '可控',
}

const loadSector = async () => {
  loading.value = true
  try {
    const res = await vibeApi.getSectors()
    const list = res?.data?.sectors || []
    sector.value = list.find(s => s.key === sectorKey.value) || null
    if (!sector.value) {
      ElMessage.warning('未找到该板块')
    }
  } catch (e: any) {
    console.error('加载板块失败:', e)
    ElMessage.error(e?.message || '加载板块失败')
  } finally {
    loading.value = false
  }
}

// 升级后的提示词：把结构化骨架完整喂给 LLM，约束输出 Markdown 三段式
const buildPrompt = (s: SectorNode) => {
  const lines: string[] = []
  lines.push(`板块：${s.label}`)
  lines.push(`定位：${s.tagline || '—'}`)
  if (s.summary) lines.push(`核心矛盾：${s.summary}`)

  if (s.layers?.length) {
    lines.push('\n# 已梳理的产业链分层骨架（请基于此深化，不要重新列举）：')
    s.layers.forEach((l, i) => {
      lines.push(`\n## ${i + 1}. ${l.name}（${l.desc}）`)
      l.nodes.forEach(n => {
        lines.push(`- ${n.name}：核心作用=${n.role}；当前焦点=${n.focus}；卡脖子等级=${bottleneckLabelMap[n.bottleneck]}`)
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
  if (!sector.value || aiLoading.value) return
  aiLoading.value = true
  aiResult.value = ''
  const prompt = buildPrompt(sector.value)
  console.log('[SectorDetail] runAiAnalysis called, prompt length:', prompt.length)
  try {
    await vibeApi.chatStream(
      [{ role: 'user', content: prompt }],
      'sector_analysis',
      (delta: string) => {
        aiResult.value += delta
      },
      (msg: string) => {
        console.error('[SectorDetail] chatStream error:', msg)
        ElMessage.error(msg || 'AI 分析出错')
      }
    )
    console.log('[SectorDetail] chatStream completed, aiResult length:', aiResult.value.length)
  } catch (e: any) {
    console.error('[SectorDetail] AI 分析失败:', e)
    ElMessage.error(e?.message || 'AI 分析失败')
  } finally {
    aiLoading.value = false
  }
}

const saveToNotes = () => {
  if (!aiResult.value || !sector.value) return
  try {
    vibeApi.saveNote(
      '问AI',
      `${sector.value.label} · AI 深度拆解`,
      aiResult.value
    )
    ElMessage.success('已存入研究记录')
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  }
}

const goBack = () => {
  router.push('/vibe/sectors')
}

onMounted(() => {
  loadSector()
})
</script>

<style lang="scss" scoped>
.sector-detail-page {
  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    color: var(--el-text-color-secondary);
    cursor: pointer;
    margin-bottom: 16px;
    user-select: none;

    &:hover {
      color: var(--el-color-primary);
    }
  }

  .detail-body {
    min-height: 200px;
  }

  .page-header {
    margin-bottom: 20px;

    .page-title {
      font-size: 24px;
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

  // ---------- 1. 核心矛盾卡片 ----------
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

  // ---------- 通用 section title ----------
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

  // ---------- 2. 产业链分层 ----------
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
      background: #2f54eb;
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
        color: #2f54eb;
        margin-right: 4px;
      }

      .focus-text {
        color: var(--el-text-color-regular);
      }
    }
  }

  // ---------- 3. 关键环节表 ----------
  .links-table {
    border-radius: 6px;
    overflow: hidden;
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

  // ---------- 4. 卡脖子点分析 ----------
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

  // ---------- 5. AI 深度拆解 ----------
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
        border-bottom: 2px solid #2f54eb;
      }

      :deep(h2) {
        font-size: 17px;
        margin: 18px 0 10px;
        padding: 6px 12px;
        background: linear-gradient(90deg, #e6f0ff 0%, transparent 100%);
        border-left: 4px solid #2f54eb;
        color: #1d39c4;
        font-weight: 600;
      }

      :deep(h3) {
        font-size: 15px;
        margin: 12px 0 6px;
        color: #2f54eb;
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
        color: #1d39c4;
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

  // ---------- 兼容旧版：核心环节标签云 ----------
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

  .disclaimer {
    margin-top: 24px;
    font-size: 12px;
    color: var(--el-text-color-placeholder);
    line-height: 1.6;
  }
}
</style>

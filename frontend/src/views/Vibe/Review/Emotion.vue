<template>
  <div class="vibe-emotion" v-loading="loading">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="title-block">
        <h1 class="page-title">
          <el-icon class="title-icon"><TrendCharts /></el-icon>
          短线情绪
        </h1>
        <p class="page-subtitle">连板梯队 / 打板情绪 · 客观公开榜单</p>
      </div>
      <el-button type="primary" plain :icon="Refresh" :loading="loading" @click="load">
        刷新
      </el-button>
    </div>

    <template v-if="emotion">
      <!-- 关键计数 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><DataLine /></el-icon> 关键计数
          </span>
          <span v-if="emotion.date" class="block-hint">数据日期：{{ emotion.date }}</span>
        </div>
        <div class="grid grid-6">
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">涨停</div>
            <div class="cnt-num up">{{ emotion.zt_count }}</div>
            <div class="cnt-sub">家</div>
            <div class="cnt-real" v-if="emotion.zt_real > 0">真实 {{ emotion.zt_real }}</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">跌停</div>
            <div class="cnt-num down">{{ emotion.dt_count }}</div>
            <div class="cnt-sub">家</div>
            <div class="cnt-real" v-if="emotion.dt_real > 0">真实 {{ emotion.dt_real }}</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">最高连板</div>
            <div class="cnt-num">{{ emotion.max_boards }}</div>
            <div class="cnt-sub">板</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">连板（2板+）</div>
            <div class="cnt-num">{{ emotion.lianban_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">炸板</div>
            <div class="cnt-num neutral">{{ emotion.zb_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
          <el-card shadow="never" class="count-card">
            <div class="cnt-label">昨涨停</div>
            <div class="cnt-num">{{ emotion.yzt_count }}</div>
            <div class="cnt-sub">家</div>
          </el-card>
        </div>
      </section>

      <!-- 打板情绪比率 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><MagicStick /></el-icon> 打板情绪比率
          </span>
        </div>
        <div class="grid grid-3">
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">封板率</div>
            <div class="rt-num up">{{ formatRate(emotion.seal_rate) }}</div>
            <div class="rt-bar">
              <div class="bar-fill up" :style="{ width: rateWidth(emotion.seal_rate) }"></div>
            </div>
          </el-card>
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">炸板率</div>
            <div class="rt-num down">{{ formatRate(emotion.break_rate) }}</div>
            <div class="rt-bar">
              <div class="bar-fill down" :style="{ width: rateWidth(emotion.break_rate) }"></div>
            </div>
          </el-card>
          <el-card shadow="never" class="ratio-card">
            <div class="rt-label">晋级率</div>
            <div class="rt-num">{{ formatRate(emotion.promotion_rate) }}</div>
            <div class="rt-bar">
              <div class="bar-fill neutral" :style="{ width: rateWidth(emotion.promotion_rate) }"></div>
            </div>
          </el-card>
        </div>
      </section>

      <!-- 连板梯队 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Sort /></el-icon> 连板梯队
          </span>
        </div>
        <el-card shadow="never" class="ladder-card">
          <div v-if="ladderText" class="ladder-text">{{ ladderText }}</div>
          <div v-else class="empty">暂无连板梯队数据</div>
        </el-card>
      </section>

      <!-- 连板股清单 -->
      <section class="block">
        <div class="block-head">
          <span class="block-title">
            <el-icon><Histogram /></el-icon> 连板股清单
          </span>
          <span class="block-hint">共 {{ emotion.lianban_stocks.length }} 只</span>
        </div>
        <el-card shadow="never" class="table-card">
          <el-table :data="emotion.lianban_stocks" stripe size="default">
            <el-table-column label="名称 / 代码" min-width="170">
              <template #default="{ row }">
                <div class="stock-cell">
                  <span class="stock-name">{{ row.name }}</span>
                  <span class="stock-code">{{ row.code }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="连板数" width="90" align="center">
              <template #default="{ row }">
                <el-tag type="danger" effect="plain">{{ row.boards }}板</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="现价" width="100" align="right">
              <template #default="{ row }">{{ row.price.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="涨停%" width="100" align="right">
              <template #default="{ row }">
                <span class="up">{{ row.pct.toFixed(2) }}%</span>
              </template>
            </el-table-column>
            <el-table-column label="成交额(亿)" width="120" align="right">
              <template #default="{ row }">{{ formatYi(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="流通市值(亿)" width="130" align="right">
              <template #default="{ row }">{{ formatYi(row.float_cap) }}</template>
            </el-table-column>
            <el-table-column label="概念" min-width="120" prop="industry" />
          </el-table>
        </el-card>
      </section>

      <p class="disclaimer">以上数据来自公开源，仅供参考，不构成投资建议</p>
    </template>

    <el-empty v-else-if="!loading" description="暂无短线情绪数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  TrendCharts,
  DataLine,
  Refresh,
  MagicStick,
  Sort,
  Histogram,
} from '@element-plus/icons-vue'
import { vibeApi, type ShortTermEmotion } from '@/api/vibe'

const loading = ref(false)
const emotion = ref<ShortTermEmotion | null>(null)

const ladderText = computed(() => {
  if (!emotion.value?.ladder?.length) return ''
  return emotion.value.ladder
    .map(l => `${l.boards}${l.plus ? '+' : ''}板: ${l.count}家`)
    .join('  |  ')
})

const formatRate = (v: number | null | undefined) =>
  v == null ? '—' : (v * 100).toFixed(1) + '%'
const rateWidth = (v: number | null | undefined) =>
  v == null ? '0%' : Math.min(100, Math.max(0, v * 100)).toFixed(1) + '%'
const formatYi = (v: number | null | undefined) =>
  v == null ? '—' : (v / 1e8).toFixed(2)

const load = async () => {
  loading.value = true
  try {
    const res = await vibeApi.getEmotion()
    emotion.value = res.data || null
    if (!emotion.value) {
      ElMessage.warning('暂无短线情绪数据')
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '数据加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
})
</script>

<style scoped>
.vibe-emotion {
  padding: 4px;
  min-height: 200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-primary);
}

.title-icon {
  color: var(--el-color-primary);
}

.page-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.block {
  margin-bottom: 24px;
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.block-title .el-icon {
  color: var(--el-color-primary);
}

.block-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-3 {
  grid-template-columns: repeat(3, 1fr);
}

.grid-4 {
  grid-template-columns: repeat(4, 1fr);
}

.grid-6 {
  grid-template-columns: repeat(6, 1fr);
}

.count-card {
  border-radius: 8px;
  text-align: center;
}

.count-card :deep(.el-card__body) {
  padding: 18px 16px;
}

.cnt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.cnt-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 32px;
  font-weight: 700;
  margin: 6px 0 2px;
  color: var(--el-text-color-primary);
}

.cnt-sub {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.cnt-real {
  font-size: 12px;
  color: var(--el-color-primary);
  margin-top: 4px;
  opacity: 0.8;
}

.ratio-card {
  border-radius: 8px;
}

.ratio-card :deep(.el-card__body) {
  padding: 18px 20px;
}

.rt-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.rt-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 28px;
  font-weight: 700;
  margin: 6px 0 12px;
  color: var(--el-text-color-primary);
}

.rt-bar {
  height: 6px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.ladder-card {
  border-radius: 8px;
}

.ladder-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  line-height: 1.8;
  color: var(--el-text-color-primary);
  letter-spacing: 0.3px;
}

.table-card {
  border-radius: 8px;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.stock-name {
  font-size: 14px;
  color: var(--el-text-color-primary);
  font-weight: 500;
}

.stock-code {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.empty {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 16px 0;
  font-size: 13px;
}

.up { color: #f56c6c; }
.down { color: #67c23a; }
.flat { color: #909399; }

.bar-fill.up { background: #f56c6c; }
.bar-fill.down { background: #67c23a; }
.bar-fill.neutral { background: #909399; }

.disclaimer {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

@media (max-width: 992px) {
  .grid-3 { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .grid-4 { grid-template-columns: repeat(2, 1fr); }
}
</style>

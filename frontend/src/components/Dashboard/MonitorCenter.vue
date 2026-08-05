<template>
  <div class="monitor-center">
    <!-- 工具栏：手动评估 + 刷新 -->
    <div class="monitor-toolbar">
      <el-button size="small" :loading="checking" @click="manualCheck">
        <el-icon><Lightning /></el-icon> 立即评估
      </el-button>
      <el-button size="small" :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
      <span class="monitor-tip">行情每 60 秒自动评估一次，命中规则后写入触发记录</span>
    </div>

    <el-row :gutter="16">
      <!-- 左栏：触发记录 -->
      <el-col :xs="24" :lg="14">
        <el-card class="monitor-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon><BellRing /></el-icon>
                <span>触发记录</span>
              </div>
              <div class="card-actions">
                <el-radio-group v-model="sourceFilter" size="small" @change="loadAlerts">
                  <el-radio-button value="all">全部</el-radio-button>
                  <el-radio-button value="signal">信号</el-radio-button>
                  <el-radio-button value="price">价格/涨跌</el-radio-button>
                  <el-radio-button value="market">市场异动</el-radio-button>
                </el-radio-group>
                <el-button v-if="alerts.length > 0" size="small" type="danger" text @click="confirmClear">
                  <el-icon><Delete /></el-icon> 清空
                </el-button>
              </div>
            </div>
          </template>

          <div v-loading="loading" class="alerts-body">
            <el-empty v-if="!loading && alerts.length === 0" description="暂无触发记录" :image-size="80">
              <p class="empty-hint">监控规则命中后，触发记录会出现在这里。可在右侧配置规则。</p>
            </el-empty>
            <div v-else class="alerts-list">
              <div v-for="alert in alerts" :key="alert.id" class="alert-item">
                <div :class="['alert-severity-bar', alert.severity || 'info']" />
                <div class="alert-main">
                  <div class="alert-top">
                    <span class="alert-symbol">{{ alert.symbol || '—' }}</span>
                    <span v-if="alert.name" class="alert-name">{{ alert.name }}</span>
                    <span v-if="alert.price != null" class="alert-price" :class="(alert.change_pct ?? 0) >= 0 ? 'up' : 'down'">
                      {{ alert.price }}
                    </span>
                    <span v-if="alert.change_pct != null" class="alert-pct" :class="alert.change_pct >= 0 ? 'up' : 'down'">
                      {{ alert.change_pct >= 0 ? '+' : '' }}{{ alert.change_pct.toFixed(2) }}%
                    </span>
                    <el-tag size="small" :type="severityTag(alert.severity)" effect="plain">
                      {{ sourceLabel(alert.source || alert.rule_type) }}
                    </el-tag>
                  </div>
                  <div class="alert-message">{{ alert.message || '命中监控规则' }}</div>
                  <div v-if="alert.conditions && alert.conditions.length" class="alert-conditions">
                    <span class="cond-label">命中</span>
                    <template v-for="(c, ci) in alert.conditions" :key="ci">
                      <span v-if="ci > 0" class="cond-logic">{{ alert.logic === 'or' ? '或' : '且' }}</span>
                      <span class="cond-item">{{ fieldLabel(c.field) }}{{ c.op === 'truth' ? '' : c.op + (c.value ?? '') }}</span>
                    </template>
                  </div>
                </div>
                <div class="alert-side">
                  <span class="alert-time">{{ formatTs(alert.ts) }}</span>
                  <el-button size="small" text type="danger" @click="deleteAlert(alert.id)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右栏：监控规则 -->
      <el-col :xs="24" :lg="10">
        <el-card class="monitor-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="card-title">
                <el-icon><List /></el-icon>
                <span>监控规则</span>
                <el-tag size="small" type="info" effect="plain">{{ rules.length }}</el-tag>
              </div>
              <div class="card-actions">
                <el-button size="small" type="primary" @click="openCreate">
                  <el-icon><Plus /></el-icon> 新建规则
                </el-button>
              </div>
            </div>
          </template>

          <div v-loading="loading" class="rules-body">
            <el-empty v-if="!loading && rules.length === 0" description="暂无监控规则" :image-size="80">
              <p class="empty-hint">点击「新建规则」配置信号、价格或市场异动监控。</p>
            </el-empty>
            <div v-else class="rules-list">
              <div v-for="rule in rules" :key="rule.id" class="rule-item" :class="{ disabled: !rule.enabled }">
                <div :class="['rule-status-bar', rule.enabled ? 'on' : 'off']" />
                <div class="rule-main">
                  <div class="rule-top">
                    <el-tag size="small" :type="typeTag(rule.type)" effect="plain">{{ typeLabel(rule.type) }}</el-tag>
                    <span class="rule-name">{{ rule.name || '未命名规则' }}</span>
                    <span v-if="!rule.enabled" class="rule-desc">已停用</span>
                  </div>
                  <div class="rule-meta">
                    <span class="rule-scope">{{ scopeLabel(rule.scope) }}</span>
                    <span v-if="rule.scope === 'symbols'" class="rule-symbols">{{ rule.symbols.join('、') }}</span>
                  </div>
                  <div v-if="rule.conditions && rule.conditions.length" class="rule-conditions">
                    <template v-for="(c, ci) in rule.conditions.slice(0, 3)" :key="ci">
                      <span v-if="ci > 0" class="cond-logic">{{ rule.logic === 'and' ? '且' : '或' }}</span>
                      <span class="cond-item">{{ fieldLabel(c.field) }}{{ c.op === 'truth' ? '' : c.op + (c.value ?? '') }}</span>
                    </template>
                    <span v-if="rule.conditions.length > 3" class="cond-more">+{{ rule.conditions.length - 3 }}</span>
                  </div>
                </div>
                <div class="rule-actions">
                  <el-button size="small" text :title="rule.enabled ? '停用' : '启用'" @click="toggleEnabled(rule)">
                    <el-icon :class="rule.enabled ? 'act-on' : ''"><Lightning /></el-icon>
                  </el-button>
                  <el-button size="small" text @click="openEdit(rule)">
                    <el-icon><EditPen /></el-icon>
                  </el-button>
                  <el-button size="small" text type="danger" @click="deleteRule(rule.id)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 规则编辑对话框 -->
    <el-dialog v-model="editorVisible" :title="editingRule ? '编辑监控规则' : '新建监控规则'" width="680px" top="6vh">
      <el-form v-if="editorVisible" label-position="top" label-width="90px">
        <el-form-item label="监控类型">
          <el-radio-group v-model="draft.type">
            <el-radio-button v-for="t in options.types" :key="t.key" :value="t.key">{{ t.label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="规则名称">
          <el-input v-model="draft.name" placeholder="留空使用默认名称" />
        </el-form-item>

        <el-form-item label="作用范围">
          <el-select v-model="draft.scope" style="width: 200px">
            <el-option v-for="s in options.scopes" :key="s.key" :value="s.key" :label="s.label" />
          </el-select>
          <el-select
            v-if="draft.scope === 'symbols'"
            v-model="draft.symbols"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入股票代码后回车"
            style="width: 320px; margin-left: 8px;"
          />
        </el-form-item>

        <el-form-item label="触发条件">
          <div class="cond-editor">
            <div class="cond-toolbar">
              <el-select v-model="draft.logic" style="width: 160px">
                <el-option v-for="l in options.logics" :key="l.key" :value="l.key" :label="l.label" />
              </el-select>
              <el-button size="small" @click="addSignalCond">+ 信号条件</el-button>
              <el-button size="small" @click="addThresholdCond">+ 阈值条件</el-button>
            </div>
            <div v-if="draft.conditions.length === 0" class="cond-empty">点击上方按钮添加触发条件</div>
            <div v-for="(cond, idx) in draft.conditions" :key="idx" class="cond-row">
              <span class="cond-logic-prefix">{{ condPrefix(idx) }}</span>
              <el-select v-model="cond.field" style="width: 200px">
                <template v-if="cond.op === 'truth'">
                  <el-option v-for="f in options.signal_fields" :key="f.key" :value="f.key" :label="f.label" />
                </template>
                <template v-else>
                  <el-option v-for="f in options.threshold_fields" :key="f.key" :value="f.key" :label="f.label" />
                </template>
              </el-select>
              <el-select v-model="cond.op" style="width: 120px">
                <el-option v-for="op in condOps(cond)" :key="op" :value="op" :label="opLabel(op)" />
              </el-select>
              <el-input-number v-if="cond.op !== 'truth'" v-model="cond.value" :step="0.01" style="width: 140px" />
              <el-button size="small" text type="danger" @click="removeCond(idx)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="冷却期(秒)">
              <el-input-number v-model="draft.cooldown_seconds" :min="0" :step="60" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="严重级别">
              <el-select v-model="draft.severity" style="width: 100%">
                <el-option v-for="s in options.severities" :key="s.key" :value="s.key" :label="s.label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="自定义提示">
              <el-input v-model="draft.message" placeholder="可留空" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Lightning, Refresh, Bell, List, Plus, Delete, EditPen,
} from '@element-plus/icons-vue'
import {
  monitorApi, genRuleId,
  type MonitorRule, type MonitorAlert, type MonitorCondition, type MonitorOptions,
} from '@/api/monitor'

const checking = ref(false)
const loading = ref(false)
const saving = ref(false)
const sourceFilter = ref<'all' | 'signal' | 'price' | 'market'>('all')
const alerts = ref<MonitorAlert[]>([])
const rules = ref<MonitorRule[]>([])
const options = reactive<MonitorOptions>({
  threshold_fields: [], signal_fields: [], operators: [],
  types: [], scopes: [], logics: [], severities: [],
})

const editorVisible = ref(false)
const editingRule = ref<MonitorRule | null>(null)
const draft = reactive<{
  id: string; name: string; enabled: boolean; type: string; scope: string;
  symbols: string[]; conditions: MonitorCondition[]; logic: string;
  cooldown_seconds: number; severity: string; message: string;
}>({
  id: '', name: '', enabled: true, type: 'signal', scope: 'symbols', symbols: [],
  conditions: [], logic: 'and', cooldown_seconds: 3600, severity: 'info', message: '',
})

let pollTimer: number | null = null

// ── 加载数据 ───────────────────────────────────────────
const loadOptions = async () => {
  try {
    const res = await monitorApi.getOptions()
    const data = (res as any)?.data ?? {}
    Object.assign(options, data)
  } catch (e) {
    console.warn('加载监控选项失败', e)
  }
}

const loadAlerts = async () => {
  try {
    const res = await monitorApi.listAlerts({
      days: 7, limit: 500,
      source: sourceFilter.value === 'all' ? undefined : sourceFilter.value,
    })
    const data = (res as any)?.data ?? {}
    alerts.value = data.alerts || []
  } catch (e) {
    console.warn('加载触发记录失败', e)
  }
}

const loadRules = async () => {
  try {
    const res = await monitorApi.listRules()
    const data = (res as any)?.data ?? {}
    rules.value = data.rules || []
  } catch (e) {
    console.warn('加载监控规则失败', e)
  }
}

const loadAll = async () => {
  loading.value = true
  await Promise.all([loadOptions(), loadAlerts(), loadRules()])
  loading.value = false
}

// ── 手动评估 ──────────────────────────────────────────
const manualCheck = async () => {
  checking.value = true
  try {
    const res = await monitorApi.manualCheck()
    const data = (res as any)?.data ?? {}
    ElMessage.success(`评估完成，触发 ${data.triggered ?? 0} 条`)
    await loadAll()
  } catch (e: any) {
    ElMessage.error('评估失败：' + (e?.message || '未知错误'))
  } finally {
    checking.value = false
  }
}

// ── 触发记录操作 ──────────────────────────────────────
const confirmClear = async () => {
  try {
    await ElMessageBox.confirm(`将删除全部 ${alerts.value.length} 条触发记录，此操作不可撤销。`, '清空触发记录', {
      type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await monitorApi.clearAlerts()
    ElMessage.success('触发记录已清空')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('清空失败：' + (e?.message || '未知错误'))
  }
}

const deleteAlert = async (id: string) => {
  try {
    await monitorApi.deleteAlert(id)
    ElMessage.success('记录已删除')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || '未知错误'))
  }
}

// ── 规则操作 ──────────────────────────────────────────
const toggleEnabled = async (rule: MonitorRule) => {
  try {
    await monitorApi.saveRule({ ...rule, enabled: !rule.enabled })
    await loadRules()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || '未知错误'))
  }
}

const deleteRule = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定删除该监控规则？', '删除规则', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await monitorApi.deleteRule(id)
    ElMessage.success('规则已删除')
    await loadRules()
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.message || '未知错误'))
  }
}

const openCreate = () => {
  editingRule.value = null
  Object.assign(draft, {
    id: genRuleId(), name: '', enabled: true, type: 'signal', scope: 'symbols',
    symbols: [], conditions: [], logic: 'and', cooldown_seconds: 3600,
    severity: 'info', message: '',
  })
  editorVisible.value = true
}

const openEdit = (rule: MonitorRule) => {
  editingRule.value = rule
  Object.assign(draft, {
    id: rule.id, name: rule.name, enabled: rule.enabled, type: rule.type, scope: rule.scope,
    symbols: [...(rule.symbols || [])],
    conditions: (rule.conditions || []).map((c) => ({ ...c })),
    logic: rule.logic || 'and', cooldown_seconds: rule.cooldown_seconds ?? 3600,
    severity: rule.severity || 'info', message: rule.message || '',
  })
  editorVisible.value = true
}

// ── 条件编辑 ──────────────────────────────────────────
const addSignalCond = () => {
  const field = options.signal_fields[0]?.key || 'signal_limit_up'
  draft.conditions.push({ field, op: 'truth' })
}
const addThresholdCond = () => {
  const field = options.threshold_fields[0]?.key || 'pct_chg'
  draft.conditions.push({ field, op: '>', value: 0 })
}
const removeCond = (idx: number) => {
  draft.conditions.splice(idx, 1)
}
const condPrefix = (idx: number) => {
  if (idx === 0) return '当'
  return draft.logic === 'and' ? '且' : '或'
}
const condOps = (cond: MonitorCondition) => {
  if (cond.op === 'truth') return ['truth']
  return options.operators.length ? options.operators : ['>', '>=', '<', '<=', '==', '!=']
}
const opLabel = (op: string) => (op === 'truth' ? '为真' : op)

const saveRule = async () => {
  if (draft.scope === 'symbols' && draft.symbols.length === 0) {
    ElMessage.warning('请至少选择一只标的')
    return
  }
  if (draft.conditions.length === 0) {
    ElMessage.warning('请至少添加一个触发条件')
    return
  }
  for (const c of draft.conditions) {
    if (c.op !== 'truth' && (c.value === null || c.value === undefined)) {
      ElMessage.warning('阈值条件需要填写数值')
      return
    }
  }
  saving.value = true
  try {
    const payload: any = {
      id: draft.id, name: draft.name, enabled: draft.enabled, type: draft.type,
      scope: draft.scope, symbols: draft.symbols, conditions: draft.conditions,
      logic: draft.logic, cooldown_seconds: draft.cooldown_seconds,
      severity: draft.severity, message: draft.message,
    }
    if (!payload.name.trim()) {
      const base = { signal: '信号监控', price: '价格监控', market: '市场异动监控' }[draft.type] || '监控规则'
      payload.name = draft.scope === 'symbols' && draft.symbols.length > 0
        ? `${base} · ${draft.symbols[0]}${draft.symbols.length > 1 ? ` 等${draft.symbols.length}只` : ''}`
        : base
    }
    await monitorApi.saveRule(payload)
    ElMessage.success('规则保存成功')
    editorVisible.value = false
    await loadRules()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.message || '未知错误'))
  } finally {
    saving.value = false
  }
}

// ── 展示辅助 ──────────────────────────────────────────
const typeLabel = (t: string) => {
  const map: Record<string, string> = { signal: '信号', price: '价格/涨跌', market: '市场异动' }
  return map[t] || t
}
const typeTag = (t: string): 'success' | 'info' | 'warning' | 'primary' => {
  const map: Record<string, any> = { signal: 'success', price: 'warning', market: 'primary' }
  return map[t] || 'info'
}
const sourceLabel = (s: string) => {
  const map: Record<string, string> = { signal: '信号', price: '价格/涨跌', market: '市场异动' }
  return map[s] || s
}
const severityTag = (s: string): 'info' | 'warning' | 'danger' => {
  const map: Record<string, any> = { info: 'info', warn: 'warning', critical: 'danger' }
  return map[s] || 'info'
}
const scopeLabel = (s: string) => (s === 'all' ? '全市场' : '指定标的')
const fieldLabel = (f: string) => {
  const all = [...options.threshold_fields, ...options.signal_fields]
  const found = all.find((item) => item.key === f)
  return found ? found.label : f
}
const formatTs = (ts: number) => {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// ── 轮询 ──────────────────────────────────────────────
const startPolling = () => {
  stopPolling()
  pollTimer = window.setInterval(() => {
    loadAlerts()
    loadRules()
  }, 30000)
}
const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  loadAll()
  startPolling()
})
onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style lang="scss" scoped>
.monitor-center {
  .monitor-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;

    .monitor-tip {
      margin-left: auto;
      font-size: 12px;
      color: var(--el-text-color-secondary);
    }
  }

  .monitor-card {
    margin-bottom: 16px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;

      .card-title {
        display: flex;
        align-items: center;
        gap: 6px;
        font-weight: 600;
      }

      .card-actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }
    }
  }

  .empty-hint {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    margin-top: 8px;
  }

  .alerts-list {
    max-height: 560px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;

    .alert-item {
      display: flex;
      gap: 10px;
      padding: 10px 12px;
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      transition: box-shadow 0.2s;

      &:hover {
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
      }

      .alert-severity-bar {
        width: 3px;
        border-radius: 2px;
        flex-shrink: 0;

        &.info { background: var(--el-color-primary); }
        &.warn { background: var(--el-color-warning); }
        &.critical { background: var(--el-color-danger); }
      }

      .alert-main {
        flex: 1;
        min-width: 0;

        .alert-top {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;

          .alert-symbol {
            font-family: monospace;
            font-weight: 600;
            font-size: 13px;
          }
          .alert-name {
            font-size: 12px;
            color: var(--el-text-color-secondary);
            max-width: 120px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
          }
          .alert-price {
            font-family: monospace;
            font-size: 13px;
            font-weight: 600;
            &.up { color: var(--el-color-danger); }
            &.down { color: var(--el-color-success); }
          }
          .alert-pct {
            font-family: monospace;
            font-size: 12px;
            &.up { color: var(--el-color-danger); }
            &.down { color: var(--el-color-success); }
          }
        }

        .alert-message {
          margin-top: 4px;
          font-size: 12px;
          color: var(--el-text-color-regular);
        }

        .alert-conditions {
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 4px;
          flex-wrap: wrap;
          font-size: 12px;

          .cond-label { color: var(--el-text-color-secondary); }
          .cond-logic { color: var(--el-text-color-secondary); }
          .cond-item {
            color: var(--el-color-primary);
            font-family: monospace;
          }
        }
      }

      .alert-side {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        justify-content: space-between;
        flex-shrink: 0;

        .alert-time {
          font-size: 11px;
          color: var(--el-text-color-placeholder);
          font-family: monospace;
        }
      }
    }
  }

  .rules-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .rule-item {
      display: flex;
      gap: 10px;
      padding: 10px 12px;
      border: 1px solid var(--el-border-color-lighter);
      border-radius: 8px;
      background: var(--el-fill-color-blank);
      transition: box-shadow 0.2s;

      &.disabled {
        opacity: 0.6;
      }

      .rule-status-bar {
        width: 3px;
        border-radius: 2px;
        flex-shrink: 0;
        &.on { background: var(--el-color-primary); }
        &.off { background: var(--el-border-color); }
      }

      .rule-main {
        flex: 1;
        min-width: 0;

        .rule-top {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;

          .rule-name {
            font-size: 13px;
            font-weight: 600;
          }
          .rule-desc {
            font-size: 11px;
            color: var(--el-text-color-secondary);
          }
        }

        .rule-meta {
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 11px;
          color: var(--el-text-color-secondary);

          .rule-symbols {
            font-family: monospace;
          }
        }

        .rule-conditions {
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 4px;
          flex-wrap: wrap;
          font-size: 12px;

          .cond-logic { color: var(--el-text-color-secondary); }
          .cond-item { color: var(--el-color-primary); font-family: monospace; }
          .cond-more { color: var(--el-text-color-secondary); }
        }
      }

      .rule-actions {
        display: flex;
        align-items: center;
        flex-shrink: 0;

        .act-on { color: var(--el-color-primary); }
      }
    }
  }

  .cond-editor {
    width: 100%;

    .cond-toolbar {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }

    .cond-empty {
      padding: 16px;
      text-align: center;
      border: 1px dashed var(--el-border-color);
      border-radius: 6px;
      color: var(--el-text-color-secondary);
      font-size: 12px;
    }

    .cond-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;

      .cond-logic-prefix {
        width: 20px;
        text-align: right;
        color: var(--el-text-color-secondary);
        font-size: 12px;
        flex-shrink: 0;
      }
    }
  }
}
</style>
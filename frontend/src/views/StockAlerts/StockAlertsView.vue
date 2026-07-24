<template>
  <div class="stock-alerts-view">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Bell /></el-icon>
        个股预警
      </h1>
      <p class="page-description">
        设置价格/涨跌幅预警，盘中自动检查并推送通知（工作日9:30-15:00每10分钟检查一次）
      </p>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <el-icon><List /></el-icon>
          <span class="panel-title">预警规则列表</span>
          <el-button size="small" type="primary" :loading="loading" @click="loadAlerts" style="margin-left:auto;">刷新</el-button>
          <el-button size="small" @click="openAddDialog">+ 新建预警</el-button>
        </div>
      </template>

      <el-table :data="alerts" v-loading="loading" stripe border style="width:100%">
        <el-table-column label="代码" width="100" prop="code" />
        <el-table-column label="名称" width="100" prop="stock_name" />
        <el-table-column label="预警类型" width="140">
          <template #default="{ row }">
            <el-tag size="small" :type="getAlertTypeTagType(row.alert_type)">{{ alertTypeLabel(row.alert_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="阈值" width="120">
          <template #default="{ row }">
            <span style="font-weight:600;">{{ formatThreshold(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="120">
          <template #default="{ row }">
            <span v-if="row.note">{{ row.note }}</span>
            <span v-else style="color:#909399;">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.triggered" type="danger" size="small">已触发</el-tag>
            <el-tag v-else-if="!row.enabled" type="info" size="small">已禁用</el-tag>
            <el-tag v-else type="success" size="small">监控中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发时间" width="160">
          <template #default="{ row }">
            <span v-if="row.triggered_at" style="font-size:12px;">{{ row.triggered_at.slice(0, 16).replace('T', ' ') }}</span>
            <span v-else style="color:#909399;">-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link @click="openEditDialog(row)">编辑</el-button>
            <el-button v-if="row.triggered" size="small" type="success" link @click="resetAlert(row)">重置</el-button>
            <el-button size="small" :type="row.enabled ? 'warning' : 'success'" link @click="toggleEnabled(row)">
              {{ row.enabled ? '禁用' : '启用' }}
            </el-button>
            <el-button size="small" type="danger" link @click="confirmDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="editDialogVisible" :title="editingId ? '编辑预警' : '新建预警'" width="460px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="股票代码" v-if="!editingId">
          <el-input v-model="editForm.code" placeholder="如 600519" />
        </el-form-item>
        <el-form-item label="股票名称" v-if="!editingId">
          <el-input v-model="editForm.stock_name" placeholder="如 贵州茅台" />
        </el-form-item>
        <el-form-item label="预警类型" v-if="!editingId">
          <el-select v-model="editForm.alert_type" style="width:100%">
            <el-option label="价格上穿" value="price_above" />
            <el-option label="价格下穿" value="price_below" />
            <el-option label="日涨幅超" value="pct_up" />
            <el-option label="日跌幅超" value="pct_down" />
            <el-option label="成交量放大" value="volume_surge" />
            <el-option label="换手率超" value="turnover_high" />
            <el-option label="振幅超" value="amplitude_high" />
            <el-option label="连涨天数" value="consecutive_up" />
            <el-option label="连跌天数" value="consecutive_down" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值">
          <el-input-number v-model="editForm.threshold" :min="0" :step="0.1" :precision="2" style="width:100%" />
          <div style="font-size:12px;color:#909399;margin-top:4px;">{{ thresholdHint }}</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAlert">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Bell, List } from '@element-plus/icons-vue'
import { stockAlertApi, type AlertRule, type AlertType, type CreateAlertPayload, type UpdateAlertPayload } from '@/api/stockAlert'

defineOptions({ name: 'StockAlertsView' })

const loading = ref(false)
const alerts = ref<AlertRule[]>([])

const loadAlerts = async () => {
  loading.value = true
  try {
    alerts.value = await stockAlertApi.getAlerts()
  } catch (e: any) {
    ElMessage.error('加载预警列表失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

// 新建/编辑
const editDialogVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const editForm = reactive<CreateAlertPayload & UpdateAlertPayload>({
  code: '',
  stock_name: '',
  alert_type: 'price_above',
  threshold: 0,
  note: '',
})

const thresholdHint = computed(() => {
  switch (editForm.alert_type) {
    case 'price_above': return '当股价≥此值时触发（单位：元）'
    case 'price_below': return '当股价≤此值时触发（单位：元）'
    case 'pct_up': return '当日涨幅≥此值时触发（单位：%）'
    case 'pct_down': return '当日跌幅≥此值时触发（单位：%）'
    case 'volume_surge': return '当日成交量≥近5日均量×此倍数时触发（如2.0=翻倍放量）'
    case 'turnover_high': return '当日换手率≥此值时触发（单位：%）'
    case 'amplitude_high': return '当日振幅≥此值时触发（单位：%）'
    case 'consecutive_up': return '连续上涨≥此天数时触发（单位：天）'
    case 'consecutive_down': return '连续下跌≥此天数时触发（单位：天）'
    default: return ''
  }
})

const openAddDialog = () => {
  editingId.value = null
  Object.assign(editForm, {
    code: '', stock_name: '', alert_type: 'price_above', threshold: 0, note: '',
  })
  editDialogVisible.value = true
}

const openEditDialog = (row: AlertRule) => {
  editingId.value = row.id
  Object.assign(editForm, {
    code: row.code, stock_name: row.stock_name, alert_type: row.alert_type,
    threshold: row.threshold, note: row.note || '',
  })
  editDialogVisible.value = true
}

const saveAlert = async () => {
  if (!editingId.value && (!editForm.code || editForm.threshold <= 0)) {
    ElMessage.warning('请填写代码和有效阈值')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      const updates: UpdateAlertPayload = {
        threshold: editForm.threshold,
        note: editForm.note,
      }
      await stockAlertApi.updateAlert(editingId.value, updates)
      ElMessage.success('预警已更新')
    } else {
      await stockAlertApi.createAlert({
        code: editForm.code,
        stock_name: editForm.stock_name,
        alert_type: editForm.alert_type as AlertType,
        threshold: editForm.threshold,
        note: editForm.note,
      })
      ElMessage.success('预警已创建')
    }
    editDialogVisible.value = false
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

const resetAlert = async (row: AlertRule) => {
  try {
    await stockAlertApi.updateAlert(row.id, { triggered: false })
    ElMessage.success('预警已重置，可再次触发')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('重置失败：' + (e?.message || e))
  }
}

const toggleEnabled = async (row: AlertRule) => {
  try {
    await stockAlertApi.updateAlert(row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? '已禁用' : '已启用')
    await loadAlerts()
  } catch (e: any) {
    ElMessage.error('操作失败：' + (e?.message || e))
  }
}

const confirmDelete = async (row: AlertRule) => {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.stock_name}(${row.code}) 的预警规则？`, '确认', { type: 'warning' })
    await stockAlertApi.deleteAlert(row.id)
    ElMessage.success('已删除')
    await loadAlerts()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败：' + (e?.message || e))
  }
}

// 工具函数
const alertTypeLabel = (t: string) => ({
  price_above: '价格上穿',
  price_below: '价格下穿',
  pct_up: '日涨幅超',
  pct_down: '日跌幅超',
  volume_surge: '成交量放大',
  turnover_high: '换手率超',
  amplitude_high: '振幅超',
  consecutive_up: '连涨天数',
  consecutive_down: '连跌天数',
}[t] || t)

const getAlertTypeTagType = (t: string) => ({
  price_above: 'danger',
  price_below: 'success',
  pct_up: 'warning',
  pct_down: 'warning',
  volume_surge: 'primary',
  turnover_high: 'primary',
  amplitude_high: 'warning',
  consecutive_up: 'danger',
  consecutive_down: 'success',
}[t] || 'info')

const formatThreshold = (row: AlertRule) => {
  if (row.alert_type.startsWith('pct_') || row.alert_type === 'turnover_high' || row.alert_type === 'amplitude_high') {
    return row.threshold.toFixed(2) + '%'
  }
  if (row.alert_type === 'volume_surge') {
    return row.threshold.toFixed(1) + '倍'
  }
  if (row.alert_type.startsWith('consecutive_')) {
    return row.threshold.toFixed(0) + '天'
  }
  return '¥' + row.threshold.toFixed(2)
}

onMounted(() => {
  loadAlerts()
})
</script>

<style lang="scss" scoped>
.stock-alerts-view { padding: 16px; }
.page-header { margin-bottom: 16px; }
.page-title {
  font-size: 24px; font-weight: 600; margin: 0 0 8px 0;
  display: flex; align-items: center; gap: 10px;
}
.page-description { margin: 0; color: var(--el-text-color-secondary); font-size: 14px; }
.card-header {
  display: flex; align-items: center; gap: 8px;
  .panel-title { font-weight: 600; }
}
</style>

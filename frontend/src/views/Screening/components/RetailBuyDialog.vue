<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="520px"
    @close="handleClose"
  >
    <el-form :model="form" label-width="110px" size="default">
      <el-form-item label="股票代码">
        <el-input :model-value="form.code" disabled />
      </el-form-item>
      <el-form-item label="股票名称">
        <el-input :model-value="form.stock_name" disabled />
      </el-form-item>
      <el-form-item label="当前价">
        <span style="font-weight:600;color:#409EFF;">¥{{ form.price?.toFixed(2) }}</span>
        <el-tag v-if="form.strategy" size="small" style="margin-left:12px;">{{ strategyLabel(form.strategy) }}</el-tag>
      </el-form-item>
      <el-form-item label="建议仓位">
        <span v-if="advice" style="color:#67C23A;font-weight:600;">
          {{ advice.suggested_shares }} 股 ≈ ¥{{ advice.suggested_amount?.toFixed(2) }}
          <span style="color:#909399;font-size:12px;margin-left:8px;">
            (目标仓位 {{ (advice.target_position_ratio * 100).toFixed(1) }}%)
          </span>
        </span>
        <el-button v-else size="small" type="primary" link :loading="calcLoading" @click="calcPosition">
          计算建议仓位
        </el-button>
      </el-form-item>
      <el-form-item label="买入数量">
        <el-input-number v-model="form.quantity" :min="100" :step="100" style="width:200px" />
        <span style="color:#909399;font-size:12px;margin-left:8px;">金额: ¥{{ buyAmount.toFixed(2) }}</span>
      </el-form-item>
      <el-form-item label="止损价">
        <el-input-number v-model="form.stop_loss_price" :precision="2" :step="0.1" :min="0" style="width:200px" />
        <span v-if="stopLossPct !== null" :style="{color: stopLossPct < -5 ? '#F56C6C' : '#909399', fontSize:'12px', marginLeft:'8px'}">
          ({{ stopLossPct.toFixed(1) }}%)
        </span>
      </el-form-item>
      <el-form-item label="止盈价">
        <el-input-number v-model="form.take_profit_price" :precision="2" :step="0.1" :min="0" style="width:200px" />
        <span v-if="takeProfitPct !== null" style="color:#67C23A;font-size:12px;margin-left:8px;">
          ({{ takeProfitPct.toFixed(1) }}%)
        </span>
      </el-form-item>
      <el-form-item label="投资逻辑">
        <el-input v-model="form.thesis" type="textarea" :rows="2" placeholder="选填：为什么买这只股票？" />
      </el-form-item>
      <el-form-item v-if="advice?.warnings?.length" label="风险提示">
        <el-alert
          v-for="(w, i) in advice.warnings"
          :key="i"
          :title="w"
          type="warning"
          :closable="false"
          style="margin-bottom:4px;"
        />
      </el-form-item>
      <el-form-item v-if="advice?.blocked" label="">
        <el-alert
          :title="`买入被阻止: ${advice.block_reasons.join('; ')}`"
          type="error"
          :closable="false"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="buyLoading"
        :disabled="advice?.blocked === true"
        @click="confirmBuy"
      >
        确认买入
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { paperApi } from '@/api/paper'
import { retailApi, type PositionAdvice } from '@/api/retail'

defineOptions({ name: 'RetailBuyDialog' })

const props = defineProps<{
  modelValue: boolean
  code: string
  stockName: string
  price: number
  strategy: string
  accountSize?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const dialogTitle = computed(() => `买入 ${props.code} - ${props.stockName}`)

const form = reactive({
  code: '',
  stock_name: '',
  price: 0,
  quantity: 100,
  stop_loss_price: null as number | null,
  take_profit_price: null as number | null,
  thesis: '',
})

const advice = ref<PositionAdvice | null>(null)
const calcLoading = ref(false)
const buyLoading = ref(false)

// 重置表单
watch(() => props.modelValue, (v) => {
  if (v) {
    form.code = props.code
    form.stock_name = props.stockName
    form.price = props.price
    form.quantity = 100
    form.stop_loss_price = null
    form.take_profit_price = null
    form.thesis = ''
    advice.value = null
    // 根据策略设置默认止损/止盈
    applyDefaultStopLoss()
    // 自动计算一次建议仓位
    calcPosition()
  }
})

// 策略默认止损/止盈比例
const STRATEGY_DEFAULTS: Record<string, { stop_loss: number; take_profit: number }> = {
  extreme_reversal: { stop_loss: -0.05, take_profit: 0.20 },
  turnaround: { stop_loss: -0.08, take_profit: 0.30 },
  small_cap_value: { stop_loss: -0.10, take_profit: 0.40 },
  convertible_arbitrage: { stop_loss: -0.05, take_profit: 0.15 },
  default: { stop_loss: -0.08, take_profit: 0.15 },
}

function applyDefaultStopLoss() {
  const cfg = STRATEGY_DEFAULTS[props.strategy] || STRATEGY_DEFAULTS.default
  form.stop_loss_price = parseFloat((props.price * (1 + cfg.stop_loss)).toFixed(2))
  form.take_profit_price = parseFloat((props.price * (1 + cfg.take_profit)).toFixed(2))
}

const stopLossPct = computed(() => {
  if (!form.price || !form.stop_loss_price) return null
  return (form.stop_loss_price - form.price) / form.price * 100
})

const takeProfitPct = computed(() => {
  if (!form.price || !form.take_profit_price) return null
  return (form.take_profit_price - form.price) / form.price * 100
})

const buyAmount = computed(() => (form.price || 0) * (form.quantity || 0))

function strategyLabel(s: string) {
  const map: Record<string, string> = {
    extreme_reversal: '极端反转',
    turnaround: '困境反转',
    small_cap_value: '小盘价值',
    convertible_arbitrage: '转债套利',
    default: '默认',
  }
  return map[s] || s
}

async function calcPosition() {
  if (!form.price) {
    ElMessage.warning('价格无效')
    return
  }
  calcLoading.value = true
  try {
    advice.value = await retailApi.calculatePosition({
      account_size: props.accountSize || 1000000,
      symbol: form.code,
      strategy: props.strategy,
      price: form.price,
    })
    // 用建议数量填充
    if (advice.value.suggested_shares > 0) {
      form.quantity = advice.value.suggested_shares
    }
    if (advice.value.blocked) {
      ElMessage.warning(`买入被阻止: ${advice.value.block_reasons.join('; ')}`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '仓位计算失败')
  } finally {
    calcLoading.value = false
  }
}

async function confirmBuy() {
  if (!form.quantity || form.quantity <= 0) {
    ElMessage.warning('请输入有效数量')
    return
  }
  buyLoading.value = true
  try {
    await paperApi.placeOrder({
      code: form.code,
      side: 'buy',
      quantity: form.quantity,
      strategy: props.strategy,
      stop_loss_price: form.stop_loss_price,
      take_profit_price: form.take_profit_price,
      thesis: form.thesis || undefined,
      stock_name: form.stock_name,
    })
    ElMessage.success(`买入成功: ${form.stock_name}(${form.code}) ${form.quantity}股`)
    visible.value = false
    emit('success')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '买入失败')
  } finally {
    buyLoading.value = false
  }
}

function handleClose() {
  visible.value = false
}
</script>

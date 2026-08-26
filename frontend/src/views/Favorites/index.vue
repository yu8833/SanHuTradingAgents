<template>
  <div class="favorites app-page">
    <!-- 顶部横幅（全局统一） -->
    <div class="page-hero">
      <div class="page-hero-main">
        <div class="page-hero-icon">
          <el-icon :size="26"><Star /></el-icon>
        </div>
        <div class="page-hero-text">
          <h2 class="page-hero-title">我的自选股</h2>
          <p class="page-hero-sub">管理您关注的股票</p>
        </div>
      </div>
    </div>

    <!-- 操作栏 -->
    <el-card class="action-card" shadow="never">
      <el-row :gutter="16" align="middle" style="margin-bottom: 16px;">
        <el-col :span="12">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索股票代码或名称"
            clearable
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>

        <el-col :span="6">
          <el-select v-model="selectedBoard" placeholder="板块" clearable>
            <el-option label="主板" value="主板" />
            <el-option label="创业板" value="创业板" />
            <el-option label="科创板" value="科创板" />
            <el-option label="北交所" value="北交所" />
          </el-select>
        </el-col>

        <el-col :span="6">
          <el-select v-model="selectedTag" placeholder="标签" clearable>
            <el-option
              v-for="tag in userTags"
              :key="tag"
              :label="tag"
              :value="tag"
            />
          </el-select>
        </el-col>
      </el-row>

      <el-row :gutter="16" align="middle">
        <el-col :span="24">
          <div class="action-buttons">
            <el-button @click="refreshData">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <!-- 只有有A股自选股时才显示同步实时行情按钮 -->
            <el-button
              v-if="hasAStocks"
              type="success"
              @click="syncAllRealtime"
              :loading="syncRealtimeLoading"
            >
              <el-icon><Refresh /></el-icon>
              同步实时行情
            </el-button>
            <!-- 只有选中的股票都是A股时才显示批量同步按钮 -->
            <el-button
              v-if="selectedStocksAreAllAShares"
              type="primary"
              @click="showBatchSyncDialog"
            >
              <el-icon><Download /></el-icon>
              批量同步数据
            </el-button>
            <el-button
              v-if="selectedStocks.length > 0"
              type="danger"
              :loading="batchDeleting"
              @click="deleteFavoritesBatch"
            >
              <el-icon><Delete /></el-icon>
              删除选中（{{ selectedStocks.length }}）
            </el-button>
            <el-button @click="openTagManager">
              标签管理
            </el-button>
            <el-button type="primary" @click="showAddDialog">
              <el-icon><Plus /></el-icon>
              添加自选股
            </el-button>
          </div>
          <div v-if="selectedStocks.length > 0" class="selection-hint">
            已选择 {{ selectedStocks.length }} 只股票，可点击「删除选中」批量操作
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 自选股列表 -->
    <el-card class="favorites-list-card" shadow="never">
      <el-table
        class="app-table app-table--trades"
        :data="filteredFavorites"
        v-loading="loading"
        style="width: 100%"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="stock_code" label="股票代码" min-width="120">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.stock_code}`" class="stock-code">{{ row.stock_code }}</router-link>
          </template>
        </el-table-column>

        <el-table-column prop="stock_name" label="股票名称" min-width="150">
          <template #default="{ row }">
            <router-link :to="`/stocks/${row.stock_code}`" class="stock-name">{{ row.stock_name }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="current_price" label="当前价格" min-width="100" sortable align="right">
          <template #default="{ row }">
            <span v-if="row.current_price !== null && row.current_price !== undefined">¥{{ fmtPrice(row.current_price) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column prop="change_percent" label="涨跌幅" min-width="100" sortable align="right">
          <template #default="{ row }">
            <span
              v-if="row.change_percent !== null && row.change_percent !== undefined"
              :class="getChangeClass(row.change_percent)"
            >
              {{ fmtPct(row.change_percent) }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column prop="return_pct" label="加入后收益率" min-width="120" sortable align="right">
          <template #default="{ row }">
            <span
              v-if="row.return_pct !== null && row.return_pct !== undefined && Number.isFinite(row.return_pct)"
              :class="getChangeClass(row.return_pct)"
            >
              {{ fmtPct(row.return_pct) }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column prop="tags" label="标签" min-width="150">
          <template #default="{ row }">
            <el-tag
              v-for="tag in row.tags"
              :key="tag"
              size="small"
              :color="getTagColor(tag)"
              effect="dark"
              :style="{ marginRight: '4px' }"
            >
              {{ tag }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="added_at" label="添加时间" min-width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.added_at) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" min-width="240" fixed="right">
          <template #default="{ row }">
            <div class="op-btns">
              <el-button
                type="text"
                size="small"
                @click="editFavorite(row)"
              >
                编辑
              </el-button>
              <!-- 只有A股显示同步按钮（兼容中小板/创业板等历史值，也用股票代码判断） -->
              <el-button
                v-if="isAStock(row)"
                type="text"
                size="small"
                @click="showSingleSyncDialog(row)"
                style="color: #2b6cb0;"
              >
                同步
              </el-button>
              <el-button
                type="text"
                size="small"
                @click="analyzeFavorite(row)"
              >
                分析
              </el-button>
              <el-button
                type="text"
                size="small"
                @click="removeFavorite(row)"
                style="color: #f56c6c;"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 空状态 -->
      <div v-if="!loading && favorites.length === 0" class="empty-state">
        <el-empty description="暂无自选股">
          <el-button type="primary" @click="showAddDialog">
            添加第一只自选股
          </el-button>
        </el-empty>
      </div>
    </el-card>

    <!-- 添加自选股对话框 -->
    <el-dialog
      v-model="addDialogVisible"
      title="添加自选股"
      width="500px"
    >
      <el-form :model="addForm" :rules="addRules" ref="addFormRef" label-width="100px">
        <el-form-item label="市场类型" prop="market">
          <el-select v-model="addForm.market" @change="handleMarketChange">
            <el-option label="A股" value="A股" />
            <el-option label="港股" value="港股" />
            <el-option label="美股" value="美股" />
          </el-select>
        </el-form-item>

        <el-form-item label="股票代码" prop="stock_code">
          <el-input
            v-model="addForm.stock_code"
            :placeholder="getStockCodePlaceholder()"
            @blur="fetchStockInfo"
          />
          <div style="font-size: 12px; color: #909399; margin-top: 4px;">
            {{ getStockCodeHint() }}
          </div>
        </el-form-item>

        <el-form-item label="股票名称" prop="stock_name">
          <el-input v-model="addForm.stock_name" placeholder="股票名称" />
          <div v-if="addForm.market !== 'A股'" style="font-size: 12px; color: #E6A23C; margin-top: 4px;">
            {{ addForm.market }}不支持自动获取，请手动输入股票名称
          </div>
        </el-form-item>

        <el-form-item label="标签">
          <el-select
            v-model="addForm.tags"
            multiple
            filterable
            allow-create
            placeholder="选择或创建标签"
          >
            <el-option v-for="tag in userTags" :key="tag" :label="tag" :value="tag">
              <span :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }">
                <span>{{ tag }}</span>
                <span :style="{ display:'inline-block', width:'12px', height:'12px', border:'1px solid #ddd', borderRadius:'2px', marginLeft:'8px', background: getTagColor(tag) }"></span>
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="备注">
          <el-input
            v-model="addForm.notes"
            type="textarea"
            :rows="2"
            placeholder="可选：添加备注信息"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="addDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleAddFavorite" :loading="addLoading">
          添加
        </el-button>
      </template>
    </el-dialog>
    <!-- 编辑自选股对话框 -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑自选股"
      width="520px"
    >
      <el-form :model="editForm" ref="editFormRef" label-width="100px">
        <el-form-item label="股票">
          <div>{{ editForm.stock_code }}｜{{ editForm.stock_name }}（{{ editForm.market }}）</div>
        </el-form-item>

        <el-form-item label="标签">
          <el-select v-model="editForm.tags" multiple filterable allow-create placeholder="选择或创建标签">
            <el-option v-for="tag in userTags" :key="tag" :label="tag" :value="tag">
              <span :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }">
                <span>{{ tag }}</span>
                <span :style="{ display:'inline-block', width:'12px', height:'12px', border:'1px solid #ddd', borderRadius:'2px', marginLeft:'8px', background: getTagColor(tag) }"></span>
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="备注">
          <el-input v-model="editForm.notes" type="textarea" :rows="2" placeholder="可选：添加备注信息" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="handleUpdateFavorite">保存</el-button>
      </template>
    </el-dialog>

    <!-- 标签管理对话框 -->
    <el-dialog v-model="tagDialogVisible" title="标签管理" width="560px">
      <el-table class="app-table app-table--compact" :data="tagList" v-loading="tagLoading" size="small" style="width: 100%; margin-bottom: 12px;">
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <template v-if="row._editing">
              <el-input v-model="row._name" placeholder="标签名称" size="small" />
            </template>
            <template v-else>
              <el-tag :color="row.color" effect="dark" style="margin-right:6px"></el-tag>
              {{ row.name }}
            </template>
          </template>
        </el-table-column>
        <el-table-column label="颜色" width="140">
          <template #default="{ row }">
            <template v-if="row._editing">
              <el-select v-model="row._color" placeholder="选择颜色" size="small" style="width: 200px">
                <el-option v-for="c in COLOR_PALETTE" :key="c" :label="c" :value="c">
                  <span :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }">
                    <span>{{ c }}</span>
                    <span :style="{ display: 'inline-block', width: '12px', height: '12px', border: '1px solid #ddd', borderRadius: '2px', marginLeft: '8px', background: c }"></span>
                  </span>
                </el-option>
              </el-select>
              <span class="color-dot-preview" :style="{ background: row._color }"></span>
            </template>
            <template v-else>
              <span :style="{display:'inline-block',width:'14px',height:'14px',background: row.color,border:'1px solid #ddd',marginRight:'6px'}"></span>
              {{ row.color }}

            </template>
          </template>
        </el-table-column>
        <el-table-column label="排序" width="100" align="center">
          <template #default="{ row }">
            <template v-if="row._editing">
              <el-input v-model.number="row._sort" type="number" size="small" />
            </template>
            <template v-else>
              {{ row.sort_order }}
            </template>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <template v-if="row._editing">
              <el-button type="text" size="small" @click="saveTag(row)">保存</el-button>
              <el-button type="text" size="small" @click="cancelEditTag(row)">取消</el-button>
            </template>
            <template v-else>
              <el-button type="text" size="small" @click="editTag(row)">编辑</el-button>
              <el-button type="text" size="small" style="color:#f56c6c" @click="deleteTag(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex; gap:8px; align-items:center;">
        <el-input v-model="newTag.name" placeholder="新标签名" style="flex:1" />
        <el-select v-model="newTag.color" placeholder="选择颜色" style="width:200px">
          <el-option v-for="c in COLOR_PALETTE" :key="c" :label="c" :value="c">
            <span :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }">
              <span>{{ c }}</span>
              <span :style="{ display: 'inline-block', width: '12px', height: '12px', border: '1px solid #ddd', borderRadius: '2px', marginLeft: '8px', background: c }"></span>
            </span>
          </el-option>
        </el-select>
        <span class="color-dot-preview" :style="{ background: newTag.color }"></span>
        <el-input v-model.number="newTag.sort_order" type="number" placeholder="排序" style="width:120px" />
        <el-button type="primary" @click="createTag" :loading="tagLoading">新增</el-button>
      </div>

      <template #footer>
        <el-button @click="tagDialogVisible=false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 批量同步对话框 -->
    <el-dialog
      v-model="batchSyncDialogVisible"
      title="批量同步股票数据"
      width="500px"
    >
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom: 16px;"
      >
        已选择 <strong>{{ selectedStocks.length }}</strong> 只股票
      </el-alert>

      <el-form :model="batchSyncForm" label-width="120px">
        <el-form-item label="同步内容">
          <el-checkbox-group v-model="batchSyncForm.syncTypes">
            <el-checkbox label="historical">历史行情数据</el-checkbox>
            <el-checkbox label="financial">财务数据</el-checkbox>
            <el-checkbox label="basic">基础数据</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="数据源">
          <el-radio-group v-model="batchSyncForm.dataSource">
            <el-radio label="tushare">Tushare</el-radio>
            <el-radio label="akshare">AKShare</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="历史数据天数" v-if="batchSyncForm.syncTypes.includes('historical')">
          <el-input-number v-model="batchSyncForm.days" :min="1" :max="3650" />
          <span style="margin-left: 10px; color: #909399; font-size: 12px;">
            (最多3650天，约10年)
          </span>
        </el-form-item>
      </el-form>

      <el-alert
        type="warning"
        :closable="false"
        style="margin-top: 16px;"
      >
        批量同步可能需要较长时间，请耐心等待
      </el-alert>

      <template #footer>
        <el-button @click="batchSyncDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleBatchSync" :loading="batchSyncLoading">
          开始同步
        </el-button>
      </template>
    </el-dialog>

    <!-- 单个股票同步对话框 -->
    <el-dialog
      v-model="singleSyncDialogVisible"
      title="同步股票数据"
      width="500px"
    >
      <el-form :model="singleSyncForm" label-width="120px">
        <el-form-item label="股票代码">
          <el-input v-model="currentSyncStock.stock_code" disabled />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="currentSyncStock.stock_name" disabled />
        </el-form-item>
        <el-form-item label="同步内容">
          <el-checkbox-group v-model="singleSyncForm.syncTypes">
            <el-checkbox label="realtime">实时行情</el-checkbox>
            <el-checkbox label="historical">历史行情数据</el-checkbox>
            <el-checkbox label="financial">财务数据</el-checkbox>
            <el-checkbox label="basic">基础数据</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="数据源">
          <el-radio-group v-model="singleSyncForm.dataSource">
            <el-radio label="tushare">Tushare</el-radio>
            <el-radio label="akshare">AKShare</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="历史数据天数" v-if="singleSyncForm.syncTypes.includes('historical')">
          <el-input-number v-model="singleSyncForm.days" :min="1" :max="3650" />
          <span style="margin-left: 10px; color: #909399; font-size: 12px;">
            (最多3650天，约10年)
          </span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="singleSyncDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSingleSync" :loading="singleSyncLoading">
          开始同步
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup lang="ts">
// 显式声明组件名，供 <keep-alive :include> 匹配
defineOptions({ name: 'FavoritesHome' })
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  Star,
  Search,
  Refresh,
  Plus,
  Download,
  Delete
} from '@element-plus/icons-vue'
import { favoritesApi } from '@/api/favorites'
import { tagsApi } from '@/api/tags'
import { stockSyncApi } from '@/api/stockSync'
import { normalizeMarketForAnalysis } from '@/utils/market'
import { ApiClient } from '@/api/request'
import { fmtPrice, fmtPct } from '@/utils/format'
import { formatDateTime } from '@/utils/datetime'

import type { FavoriteItem } from '@/api/favorites'
import { useAuthStore } from '@/stores/auth'


// 颜色可选项（20种预设颜色）
const COLOR_PALETTE = [
  '#2b6cb0', '#2c5282', '#5c90c2', '#52C41A', '#67C23A',
  '#13C2C2', '#FA8C16', '#E6A23C', '#F56C6C', '#EB2F96',
  '#722ED1', '#8E44AD', '#00BFBF', '#1F2D3D', '#606266',
  '#909399', '#C0C4CC', '#FF7F50', '#A0CFFF', '#2C3E50'
]

const router = useRouter()

// 响应式数据
const loading = ref(false)
const favorites = ref<FavoriteItem[]>([])
const userTags = ref<string[]>([])
const tagColorMap = ref<Record<string, string>>({})
const getTagColor = (name: string) => tagColorMap.value[name] || ''

const searchKeyword = ref('')
const selectedTag = ref('')
const selectedBoard = ref('')
const batchDeleting = ref(false)

// 批量选择
const selectedStocks = ref<FavoriteItem[]>([])

// 批量同步对话框
const batchSyncDialogVisible = ref(false)
const batchSyncLoading = ref(false)
const batchSyncForm = ref({
  syncTypes: ['historical', 'financial'],
  dataSource: 'tushare' as 'tushare' | 'akshare',
  days: 365
})

// 单个股票同步对话框
const singleSyncDialogVisible = ref(false)
const singleSyncLoading = ref(false)
const currentSyncStock = ref({
  stock_code: '',
  stock_name: ''
})
const singleSyncForm = ref({
  syncTypes: ['realtime'],  // 默认只选中实时行情（最常用）
  dataSource: 'tushare' as 'tushare' | 'akshare',
  days: 365
})

// 添加对话框
const addDialogVisible = ref(false)
const addLoading = ref(false)
const addFormRef = ref()
const addForm = ref({
  stock_code: '',
  stock_name: '',
  market: 'A股',
  tags: [],
  notes: ''
})

// 股票代码验证器
const validateStockCode = (_rule: any, value: any, callback: any) => {
  if (!value) {
    callback(new Error('请输入股票代码'))
    return
  }

  const code = value.trim()
  const market = addForm.value.market

  if (market === 'A股') {
    // A股：6位数字
    if (!/^\d{6}$/.test(code)) {
      callback(new Error('A股代码必须是6位数字，如：000001'))
      return
    }
  } else if (market === '港股') {
    // 港股：4位数字 或 4-5位数字+.HK
    if (!/^\d{4,5}$/.test(code) && !/^\d{4,5}\.HK$/i.test(code)) {
      callback(new Error('港股代码格式：4位数字（如：0700）或带后缀（如：0700.HK）'))
      return
    }
  } else if (market === '美股') {
    // 美股：1-5个字母
    if (!/^[A-Z]{1,5}$/i.test(code)) {
      callback(new Error('美股代码必须是1-5个字母，如：AAPL'))
      return
    }
  }

  callback()
}

const addRules = {
  market: [
    { required: true, message: '请选择市场类型', trigger: 'change' }
  ],
  stock_code: [
    { required: true, message: '请输入股票代码', trigger: 'blur' },
    { validator: validateStockCode, trigger: 'blur' }
  ],
  stock_name: [
    { required: true, message: '请输入股票名称', trigger: 'blur' }
  ]
}

// 编辑对话框
const editDialogVisible = ref(false)
const editLoading = ref(false)
const editFormRef = ref()
const editForm = ref({
  stock_code: '',
  stock_name: '',
  market: 'A股',
  tags: [] as string[],
  notes: ''
})


// 计算属性
const filteredFavorites = computed<FavoriteItem[]>(() => {
  let result: FavoriteItem[] = favorites.value

  // 关键词搜索
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    result = result.filter((item: FavoriteItem) =>
      (item.stock_code || '').toLowerCase().includes(keyword) ||
      (item.stock_name || '').toLowerCase().includes(keyword)
    )
  }

  // 板块筛选
  if (selectedBoard.value) {
    result = result.filter((item: FavoriteItem) =>
      item.board === selectedBoard.value
    )
  }

  // 标签筛选
  if (selectedTag.value) {
    result = result.filter((item: FavoriteItem) =>
      (item.tags || []).includes(selectedTag.value)
    )
  }

  return result
})

// 判断是否为 A 股（兼顾 market 字段和股票代码）
const isAStock = (row: any) => {
  if (!row) return false
  const m = String(row.market || '').trim()
  if (m === 'A股') return true
  // 兼容中小板/创业板/主板/科创板/北交所 这类板块值
  if (['主板','创业板','科创板','中小板','北交所','上海','深圳','上交所','深交所','沪市','深市'].includes(m)) {
    return true
  }
  // 用股票代码兜底判断
  const code = String(row.stock_code || '').trim().toUpperCase()
  return /^\d{6}$/.test(code)
}

// 判断是否有A股自选股
const hasAStocks = computed(() => {
  return favorites.value.some(item => isAStock(item))
})

// 判断选中的股票是否都是A股
const selectedStocksAreAllAShares = computed(() => {
  if (selectedStocks.value.length === 0) return false
  return selectedStocks.value.every(item => isAStock(item))
})

// 方法
const loadFavorites = async () => {
  loading.value = true
  try {
    const res = await favoritesApi.list()
    favorites.value = ((res as any)?.data || []) as FavoriteItem[]
  } catch (error: any) {
    console.error('加载自选股失败:', error)
    ElMessage.error(error.message || '加载自选股失败')
  } finally {
    loading.value = false
  }
}

// 同步实时行情
const syncRealtimeLoading = ref(false)
const syncAllRealtime = async () => {
  if (favorites.value.length === 0) {
    ElMessage.warning('没有自选股需要同步')
    return
  }

  syncRealtimeLoading.value = true
  try {
    const res = await favoritesApi.syncRealtime('tushare')
    const data = (res as any)?.data

    if ((res as any)?.success) {
      ElMessage.success(data?.message || `同步完成: 成功 ${data?.success_count} 只`)
      // 重新加载自选股列表以获取最新价格
      await loadFavorites()
    } else {
      ElMessage.error((res as any)?.message || '同步失败')
    }
  } catch (error: any) {
    console.error('同步实时行情失败:', error)
    ElMessage.error(error.message || '同步失败，请稍后重试')
  } finally {
    syncRealtimeLoading.value = false
  }
}

const loadUserTags = async () => {
  try {
    const [customRes, favoritesRes] = await Promise.allSettled([
      tagsApi.list(),
      favoritesApi.tags()
    ])

    const customTags = customRes.status === 'fulfilled' ? ((customRes.value as any)?.data || []) : []
    const favoriteTags = favoritesRes.status === 'fulfilled' ? ((favoritesRes.value as any)?.data || []) : []

    const tagNames = new Set<string>()
    const colorMap: Record<string, string> = {}

    if (Array.isArray(customTags)) {
      customTags.forEach((t: any) => {
        if (t?.name) {
          tagNames.add(t.name)
          if (t.color) colorMap[t.name] = t.color
        }
      })
    }

    if (Array.isArray(favoriteTags)) {
      favoriteTags.forEach((name: string) => {
        if (name) tagNames.add(name)
      })
    }

    userTags.value = Array.from(tagNames).sort()
    tagColorMap.value = colorMap
  } catch (error) {
    console.error('加载标签失败:', error)
    userTags.value = []
    tagColorMap.value = {}
  }
}

// 标签管理对话框 - 脚本
const tagDialogVisible = ref(false)
const tagLoading = ref(false)
const tagList = ref<any[]>([])
const newTag = ref({ name: '', color: '#2b6cb0', sort_order: 0 })

const loadTagList = async () => {
  tagLoading.value = true
  try {
    const res = await tagsApi.list()
    tagList.value = (res as any)?.data || []
  } catch (e) {
    console.error('加载标签列表失败:', e)
  } finally {
    tagLoading.value = false
  }
}

const openTagManager = async () => {
  tagDialogVisible.value = true
  await loadTagList()
}

const createTag = async () => {
  if (!newTag.value.name || !newTag.value.name.trim()) {
    ElMessage.warning('请输入标签名')
    return
  }
  tagLoading.value = true
  try {
    await tagsApi.create({ ...newTag.value })
    ElMessage.success('创建成功')
    newTag.value = { name: '', color: '#2b6cb0', sort_order: 0 }
    await loadTagList()
    await loadUserTags()
  } catch (e: any) {
    console.error('创建标签失败:', e)
    ElMessage.error(e?.message || '创建失败')
  } finally {
    tagLoading.value = false
  }
}

const editTag = (row: any) => {
  row._editing = true
  row._name = row.name
  row._color = row.color
  row._sort = row.sort_order
}

const cancelEditTag = (row: any) => {
  row._editing = false
}

const saveTag = async (row: any) => {
  tagLoading.value = true
  try {
    await tagsApi.update(row.id, {
      name: row._name ?? row.name,
      color: row._color ?? row.color,
      sort_order: row._sort ?? row.sort_order,
    })
    ElMessage.success('保存成功')
    row._editing = false
    await loadTagList()
    await loadUserTags()
  } catch (e: any) {
    console.error('保存标签失败:', e)
    ElMessage.error(e?.message || '保存失败')
  } finally {
    tagLoading.value = false
  }
}

const deleteTag = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确定删除标签 ${row.name} 吗？`, '删除标签', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    tagLoading.value = true
    await tagsApi.remove(row.id)
    ElMessage.success('已删除')
    await loadTagList()
    await loadUserTags()
  } catch (e) {
    // 用户取消或失败
  } finally {
    tagLoading.value = false
  }
}



const refreshData = () => {
  loadFavorites()
  loadUserTags()
}

const showAddDialog = () => {
  addForm.value = {
    stock_code: '',
    stock_name: '',
    market: 'A股',
    tags: [],
    notes: ''
  }
  addDialogVisible.value = true
}

// 市场类型切换时清空股票代码和名称
const handleMarketChange = () => {
  addForm.value.stock_code = ''
  addForm.value.stock_name = ''
  // 清除验证错误
  if (addFormRef.value) {
    addFormRef.value.clearValidate(['stock_code', 'stock_name'])
  }
}

// 获取股票代码输入提示
const getStockCodePlaceholder = () => {
  const market = addForm.value.market
  if (market === 'A股') {
    return '请输入6位数字代码，如：000001'
  } else if (market === '港股') {
    return '请输入4位数字代码，如：0700'
  } else if (market === '美股') {
    return '请输入股票代码，如：AAPL'
  }
  return '请输入股票代码'
}

// 获取股票代码输入提示文字
const getStockCodeHint = () => {
  const market = addForm.value.market
  if (market === 'A股') {
    return '输入代码后失焦，将自动填充股票名称'
  } else if (market === '港股') {
    return '港股不支持自动获取名称，请手动输入'
  } else if (market === '美股') {
    return '美股不支持自动获取名称，请手动输入'
  }
  return ''
}

const fetchStockInfo = async () => {
  if (!addForm.value.stock_code) return

  try {
    const symbol = addForm.value.stock_code.trim()
    const market = addForm.value.market

    // 🔥 只有A股支持自动获取股票名称
    if (market === 'A股') {
      // 从后台获取股票基础信息
      const res = await ApiClient.get(`/api/stock-data/basic-info/${symbol}`)

      if ((res as any)?.success && (res as any)?.data) {
        const stockInfo = (res as any).data
        // 自动填充股票名称
        if (stockInfo.name) {
          addForm.value.stock_name = stockInfo.name
          ElMessage.success(`已自动填充股票名称: ${stockInfo.name}`)
        }
      } else {
        ElMessage.warning('未找到该股票信息，请手动输入股票名称')
      }
    }
    // 港股和美股不调用API，用户需要手动输入
  } catch (error: any) {
    console.error('获取股票信息失败:', error)
    ElMessage.warning('获取股票信息失败，请手动输入股票名称')
  }
}

const handleAddFavorite = async () => {
  try {
    await addFormRef.value.validate()
    addLoading.value = true
    const payload = { ...addForm.value }
    const res = await favoritesApi.add(payload as any)
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '添加失败')
    ElMessage.success('添加成功')
    addDialogVisible.value = false
    await loadFavorites()
  } catch (error: any) {
    console.error('添加自选股失败:', error)
    ElMessage.error(error.message || '添加失败')
  } finally {
    addLoading.value = false
  }
}

const handleUpdateFavorite = async () => {
  try {
    editLoading.value = true
    const payload = {
      tags: editForm.value.tags,
      notes: editForm.value.notes
    }
    const res = await favoritesApi.update(editForm.value.stock_code, payload as any)
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '更新失败')
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    await loadFavorites()
  } catch (error: any) {
    console.error('更新自选股失败:', error)
    ElMessage.error(error.message || '保存失败')
  } finally {
    editLoading.value = false
  }
}


const editFavorite = (row: any) => {
  editForm.value = {
    stock_code: row.stock_code,
    stock_name: row.stock_name,
    market: row.market || 'A股',
    tags: Array.isArray(row.tags) ? [...row.tags] : [],
    notes: row.notes || ''
  }
  editDialogVisible.value = true
}

const analyzeFavorite = (row: any) => {
  router.push({
    name: 'SingleAnalysis',
    query: { stock: row.stock_code, market: normalizeMarketForAnalysis(row.market || 'A股') }
  })
}

const removeFavorite = async (row: any) => {
  try {
    await ElMessageBox.confirm(
      `确定要从自选股中删除 ${row.stock_name} 吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    const res = await favoritesApi.remove(row.stock_code)
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '删除失败')
    ElMessage.success('删除成功')
    await loadFavorites()
  } catch (e) {
    // 用户取消或失败
  }
}

const deleteFavoritesBatch = async () => {
  if (selectedStocks.value.length === 0) {
    ElMessage.warning('请先选择要删除的股票')
    return
  }
  const names = selectedStocks.value.map(s => `${s.stock_code}（${s.stock_name}）`).join('、')
  try {
    await ElMessageBox.confirm(
      `确定从自选股中删除以下 ${selectedStocks.value.length} 只股票吗？\n${names}`,
      '批量删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
        distinguishCancelAndClose: true
      }
    )
    const codes = selectedStocks.value
      .map(s => s.stock_code)
      .filter((c): c is string => Boolean(c))
    batchDeleting.value = true
    const res = await favoritesApi.removeBatch(codes)
    if ((res as any)?.success === false) throw new Error((res as any)?.message || '批量删除失败')
    const deleted = ((res as any)?.data?.deleted) ?? codes.length
    ElMessage.success(`已删除 ${deleted} 只自选股`)
    await loadFavorites()
  } catch (e: any) {
    if (e === 'cancel' || e?.message === 'cancel') return
    if (typeof e === 'string' || !e?.message) return
    ElMessage.error(e?.message || '批量删除失败')
  } finally {
    batchDeleting.value = false
  }
}

const viewStockDetail = (row: any) => {
  router.push({
    name: 'StockDetail',
    params: { code: String(row.stock_code || '').toUpperCase() }
  })
}

// 处理表格选择变化
const handleSelectionChange = (selection: FavoriteItem[]) => {
  selectedStocks.value = selection
}

// 显示单个股票同步对话框
const showSingleSyncDialog = (row: FavoriteItem) => {
  currentSyncStock.value = {
    stock_code: row.stock_code || '',
    stock_name: row.stock_name || ''
  }
  singleSyncDialogVisible.value = true
}

// 执行单个股票同步
const handleSingleSync = async () => {
  if (singleSyncForm.value.syncTypes.length === 0) {
    ElMessage.warning('请至少选择一种同步内容')
    return
  }

  singleSyncLoading.value = true
  try {
    const res = await stockSyncApi.syncSingle({
      symbol: currentSyncStock.value.stock_code,
      sync_realtime: singleSyncForm.value.syncTypes.includes('realtime'),
      sync_historical: singleSyncForm.value.syncTypes.includes('historical'),
      sync_financial: singleSyncForm.value.syncTypes.includes('financial'),
      data_source: singleSyncForm.value.dataSource,
      days: singleSyncForm.value.days
    })

    if (res.success) {
      const data = res.data
      let message = `股票 ${currentSyncStock.value.stock_code} 数据同步完成\n`

      if (data.realtime_sync) {
        if (data.realtime_sync.success) {
          message += `✅ 实时行情同步成功\n`
        } else {
          message += `❌ 实时行情同步失败: ${data.realtime_sync.error || '未知错误'}\n`
        }
      }

      if (data.historical_sync) {
        if (data.historical_sync.success) {
          message += `✅ 历史数据: ${data.historical_sync.records || 0} 条记录\n`
        } else {
          message += `❌ 历史数据同步失败: ${data.historical_sync.error || '未知错误'}\n`
        }
      }

      if (data.financial_sync) {
        if (data.financial_sync.success) {
          message += `✅ 财务数据同步成功\n`
        } else {
          message += `❌ 财务数据同步失败: ${data.financial_sync.error || '未知错误'}\n`
        }
      }

      if (data.basic_sync) {
        if (data.basic_sync.success) {
          message += `✅ 基础数据同步成功\n`
        } else {
          message += `❌ 基础数据同步失败: ${data.basic_sync.error || '未知错误'}\n`
        }
      }

      ElMessage.success(message)
      singleSyncDialogVisible.value = false

      // 刷新列表
      await loadFavorites()
    } else {
      ElMessage.error(res.message || '同步失败')
    }
  } catch (error: any) {
    console.error('同步失败:', error)
    ElMessage.error(error.message || '同步失败，请稍后重试')
  } finally {
    singleSyncLoading.value = false
  }
}

// 显示批量同步对话框
const showBatchSyncDialog = () => {
  if (selectedStocks.value.length === 0) {
    ElMessage.warning('请先选择要同步的股票')
    return
  }
  batchSyncDialogVisible.value = true
}

// 执行批量同步
const handleBatchSync = async () => {
  if (batchSyncForm.value.syncTypes.length === 0) {
    ElMessage.warning('请至少选择一种同步内容')
    return
  }

  batchSyncLoading.value = true
  try {
    const symbols = selectedStocks.value
      .map(stock => stock.stock_code)
      .filter((code): code is string => Boolean(code))

    const res = await stockSyncApi.syncBatch({
      symbols,
      sync_historical: batchSyncForm.value.syncTypes.includes('historical'),
      sync_financial: batchSyncForm.value.syncTypes.includes('financial'),
      data_source: batchSyncForm.value.dataSource,
      days: batchSyncForm.value.days
    })

    if (res.success) {
      const data = res.data
      let message = `批量同步完成 (共 ${symbols.length} 只股票)\n`

      if (data.historical_sync) {
        message += `✅ 历史数据: ${data.historical_sync.success_count}/${data.historical_sync.success_count + data.historical_sync.error_count} 成功，共 ${data.historical_sync.total_records} 条记录\n`
      }

      if (data.financial_sync) {
        message += `✅ 财务数据: ${data.financial_sync.success_count}/${data.financial_sync.total_symbols} 成功\n`
      }

      if (data.basic_sync) {
        message += `✅ 基础数据: ${data.basic_sync.success_count}/${data.basic_sync.total_symbols} 成功\n`
      }

      ElMessage.success(message)
      batchSyncDialogVisible.value = false

      // 刷新列表
      await loadFavorites()
    } else {
      ElMessage.error(res.message || '批量同步失败')
    }
  } catch (error: any) {
    console.error('批量同步失败:', error)
    ElMessage.error(error.message || '批量同步失败，请稍后重试')
  } finally {
    batchSyncLoading.value = false
  }
}

const getChangeClass = (changePercent: number) => {
  if (changePercent > 0) return 'text-red'
  if (changePercent < 0) return 'text-green'
  return ''
}


// 生命周期
onMounted(() => {
  const auth = useAuthStore()
  if (auth.isAuthenticated) {
    loadFavorites()
    loadUserTags()
  }
})
</script>

<style lang="scss" scoped>
.favorites {
  .action-card {
    margin-bottom: 24px;

    .action-buttons {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .selection-hint {
      margin-top: 10px;
      font-size: 13px;
      color: #e6a23c;
      background: #fdf6ec;
      border: 1px solid #faecd8;
      padding: 8px 12px;
      border-radius: 6px;
    }
  }

  /* 颜色选项样式 */
  .color-dot {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 1px solid #ddd;
    border-radius: 2px;
    margin-left: 8px;
    vertical-align: middle;
  }
  .color-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
  }
  .color-dot-preview {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 1px solid #ddd;
    border-radius: 2px;
    margin-left: 6px;
    vertical-align: middle;
  }

  .favorites-list-card {
    .empty-state {
      padding: 40px;
      text-align: center;
    }

    .text-red {
      color: #f56c6c;
    }

    .text-green {
      color: #67c23a;
    }

    /* 所有单元格不换行，保持单行显示 */
    :deep(.el-table__cell .cell) {
      white-space: nowrap;
    }

    /* 操作按钮保持单行 */
    .op-btns {
      display: flex;
      align-items: center;
      flex-wrap: nowrap;
      gap: 4px;
      white-space: nowrap;
    }
  }
}

/* ============ 响应式：手机端适配 ============ */
@media (max-width: 768px) {
  .favorites {
    .action-card {
      :deep(.el-col) {
        flex: 0 0 100%;
        max-width: 100%;
        margin-bottom: 8px;
      }
      .action-buttons {
        flex-wrap: wrap;
        gap: 8px;
        justify-content: flex-start;
      }
      .action-buttons .el-button {
        flex: 1 1 auto;
        min-width: calc(50% - 4px);
      }
    }

    .favorites-list-card {
      .op-btns {
        gap: 2px;
      }
      .op-btns .el-button {
        padding: 6px 4px;
        font-size: 12px;
      }
    }
  }
}
</style>
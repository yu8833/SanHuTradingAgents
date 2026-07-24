<template>
  <div class="notifications-page">
    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <span>通知中心</span>
            <el-tag v-if="unreadCount > 0" type="danger" size="small">{{ unreadCount }} 未读</el-tag>
          </div>
          <div style="display: flex; gap: 8px;">
            <el-radio-group v-model="filterStatus" size="small" @change="loadData">
              <el-radio-button value="unread">未读</el-radio-button>
              <el-radio-button value="all">全部</el-radio-button>
            </el-radio-group>
            <el-button text @click="handleMarkAllRead" :disabled="unreadCount === 0">全部已读</el-button>
            <el-button text @click="loadData">刷新</el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="filterType" @tab-change="loadData">
        <el-tab-pane label="全部" name="" />
        <el-tab-pane label="分析" name="analysis" />
        <el-tab-pane label="预警" name="alert" />
        <el-tab-pane label="系统" name="system" />
      </el-tabs>

      <el-empty v-if="notifications.length === 0" description="暂无通知" />
      <div v-else class="notification-list">
        <div
          v-for="n in notifications"
          :key="n.id"
          class="notification-item"
          :class="{ unread: n.status === 'unread' }"
          @click="handleClickItem(n)"
        >
          <div class="noti-icon">
            <el-icon :size="20" :color="getIconColor(n.type)">
              <component :is="getIconName(n.type)" />
            </el-icon>
          </div>
          <div class="noti-body">
            <div class="noti-title">
              {{ n.title }}
              <el-tag v-if="n.status === 'unread'" type="danger" size="small" effect="dark">未读</el-tag>
            </div>
            <div class="noti-content" v-if="n.content">{{ n.content }}</div>
            <div class="noti-meta">
              <el-tag size="small" :type="getTypeTagType(n.type)" effect="plain">{{ getTypeLabel(n.type) }}</el-tag>
              <span v-if="n.source" class="noti-source">{{ n.source }}</span>
              <span class="noti-time">{{ formatTime(n.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="notifications.length > 0" style="margin-top: 16px; text-align: center;">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="loadData"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Bell, DataAnalysis, Warning, Setting } from '@element-plus/icons-vue'
import { notificationsApi, type NotificationItem } from '@/api/notifications'

defineOptions({ name: 'NotificationsPage' })

const notifications = ref<NotificationItem[]>([])
const unreadCount = ref(0)
const filterStatus = ref<'unread' | 'all'>('all')
const filterType = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

function getIconName(type: string) {
  if (type === 'analysis') return DataAnalysis
  if (type === 'alert') return Warning
  if (type === 'system') return Setting
  return Bell
}

function getIconColor(type: string): string {
  if (type === 'analysis') return '#409eff'
  if (type === 'alert') return '#e6a23c'
  if (type === 'system') return '#909399'
  return '#409eff'
}

function getTypeLabel(type: string): string {
  if (type === 'analysis') return '分析'
  if (type === 'alert') return '预警'
  if (type === 'system') return '系统'
  return '通知'
}

function getTypeTagType(type: string): any {
  if (type === 'analysis') return 'primary'
  if (type === 'alert') return 'warning'
  if (type === 'system') return 'info'
  return ''
}

function formatTime(time: string): string {
  if (!time) return ''
  const d = new Date(time)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`
}

async function loadData() {
  try {
    const res = await notificationsApi.getList({
      status: filterStatus.value,
      page: page.value,
      page_size: pageSize.value,
      type: filterType.value || undefined,
    })
    const data = (res as any)?.data || {}
    notifications.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    console.error('加载通知失败', e)
  }
  try {
    const res2 = await notificationsApi.getUnreadCount()
    unreadCount.value = (res2 as any)?.data?.count || 0
  } catch (e) { /* ignore */ }
}

async function handleClickItem(n: NotificationItem) {
  if (n.status === 'unread') {
    try {
      await notificationsApi.markRead(n.id)
      n.status = 'read'
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    } catch (e) { /* ignore */ }
  }
}

async function handleMarkAllRead() {
  try {
    await notificationsApi.markAllRead()
    notifications.value.forEach(n => n.status = 'read')
    unreadCount.value = 0
    ElMessage.success('已全部标记为已读')
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.notifications-page { padding: 0; }
.notification-list { display: flex; flex-direction: column; gap: 8px; }
.notification-item { display: flex; gap: 12px; padding: 12px; border-radius: 6px; border: 1px solid var(--el-border-color-lighter); cursor: pointer; transition: background 0.2s; }
.notification-item:hover { background: var(--el-fill-color-light); }
.notification-item.unread { border-left: 3px solid var(--el-color-primary); background: var(--el-color-primary-light-9); }
.noti-icon { flex-shrink: 0; padding-top: 2px; }
.noti-body { flex: 1; min-width: 0; }
.noti-title { font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 8px; }
.noti-content { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 4px; line-height: 1.5; }
.noti-meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.noti-source { font-size: 12px; color: var(--el-text-color-secondary); }
.noti-time { margin-left: auto; font-size: 12px; color: var(--el-text-color-placeholder); }
</style>

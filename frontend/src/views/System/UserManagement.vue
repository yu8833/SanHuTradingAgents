<template>
  <div class="user-management">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><UserFilled /></el-icon>
        用户管理
      </h1>
      <p class="page-description">
        管理系统用户、权限和配额
      </p>
    </div>

    <!-- 统计概览 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value">{{ stats.total }}</div>
            <div class="stat-label">总用户数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value stat-active">{{ stats.active }}</div>
            <div class="stat-label">活跃用户</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value stat-admin">{{ stats.admins }}</div>
            <div class="stat-label">管理员</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-content">
            <div class="stat-value stat-disabled">{{ stats.disabled }}</div>
            <div class="stat-label">已禁用</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 工具栏 -->
    <el-card class="toolbar" shadow="never">
      <div class="toolbar-content">
        <div class="toolbar-left">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索用户名或邮箱"
            style="width: 250px"
            clearable
            @keyup.enter="filterUsers"
            @clear="filterUsers"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select v-model="filterStatus" placeholder="状态筛选" style="width: 120px; margin-left: 10px" @change="filterUsers">
            <el-option label="全部状态" value="" />
            <el-option label="活跃" :value="true" />
            <el-option label="已禁用" :value="false" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            创建用户
          </el-button>
          <el-button @click="loadUsers" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>
    </el-card>

    <!-- 用户列表 -->
    <el-card shadow="never">
      <el-table
        :data="filteredUsers"
        v-loading="loading"
        style="width: 100%"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
      >
        <el-table-column prop="username" label="用户名" min-width="120" sortable>
          <template #default="{ row }">
            <div class="user-cell">
              <el-avatar :size="32" :icon="UserFilled" />
              <span class="username">{{ row.username }}</span>
              <el-tag v-if="row.is_admin" type="danger" size="small">管理员</el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="email" label="邮箱" min-width="180" />

        <el-table-column prop="is_active" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '活跃' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="total_analyses" label="分析次数" width="100" align="center" sortable>
          <template #default="{ row }">
            {{ row.total_analyses || 0 }}
          </template>
        </el-table-column>

        <el-table-column prop="daily_quota" label="每日配额" width="100" align="center" />

        <el-table-column prop="concurrent_limit" label="并发限制" width="100" align="center" />

        <el-table-column prop="last_login" label="最后登录" width="170" sortable>
          <template #default="{ row }">
            {{ row.last_login ? formatDateTime(row.last_login) : '从未登录' }}
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="注册时间" width="170" sortable>
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              :type="row.is_active ? 'warning' : 'success'"
              plain
              @click="toggleUserStatus(row)"
              :disabled="row.username === currentUsername"
            >
              {{ row.is_active ? '禁用' : '激活' }}
            </el-button>
            <el-button
              size="small"
              type="primary"
              plain
              @click="openEditDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              size="small"
              type="info"
              plain
              @click="openResetPasswordDialog(row)"
            >
              重置密码
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              @click="confirmDeleteUser(row)"
              :disabled="row.username === currentUsername || row.is_admin"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建用户对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      title="创建用户"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="80px"
      >
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="3-50个字符" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="createForm.password"
            type="password"
            placeholder="至少6位密码"
            show-password
          />
        </el-form-item>
        <el-form-item label="管理员">
          <el-switch v-model="createForm.is_admin" />
          <span class="form-hint">管理员拥有系统管理权限</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateUser" :loading="createLoading">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑用户对话框 -->
    <el-dialog
      v-model="showEditDialog"
      title="编辑用户"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="editFormRef"
        :model="editForm"
        label-width="100px"
      >
        <el-form-item label="用户名">
          <el-input :value="editForm.username" disabled />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input :value="editForm.email" disabled />
        </el-form-item>
        <el-form-item label="每日配额">
          <el-input-number v-model="editForm.daily_quota" :min="0" :max="100000" :step="100" />
        </el-form-item>
        <el-form-item label="并发限制">
          <el-input-number v-model="editForm.concurrent_limit" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="管理员权限">
          <el-switch v-model="editForm.is_admin" :disabled="editForm.username === currentUsername" />
          <span class="form-hint">注意：取消管理员权限后该用户将无法访问管理功能</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleEditUser" :loading="editLoading">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 重置密码对话框 -->
    <el-dialog
      v-model="showResetPasswordDialog"
      title="重置密码"
      width="440px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="重置密码后，请将新密码告知用户。"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      />
      <el-form
        ref="resetPasswordFormRef"
        :model="resetPasswordForm"
        :rules="resetPasswordRules"
        label-width="80px"
      >
        <el-form-item label="用户名">
          <el-input :value="resetPasswordForm.username" disabled />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input
            v-model="resetPasswordForm.new_password"
            type="password"
            placeholder="至少6位密码"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm_password">
          <el-input
            v-model="resetPasswordForm.confirm_password"
            type="password"
            placeholder="请再次输入密码"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showResetPasswordDialog = false">取消</el-button>
        <el-button type="primary" @click="handleResetPassword" :loading="resetPasswordLoading">
          重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { UserFilled, Search, Plus, Refresh } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const currentUsername = computed(() => authStore.user?.username || '')

// 用户列表
const users = ref<any[]>([])
const loading = ref(false)
const searchKeyword = ref('')
const filterStatus = ref<boolean | string>('')

// 统计
const stats = computed(() => ({
  total: users.value.length,
  active: users.value.filter(u => u.is_active).length,
  admins: users.value.filter(u => u.is_admin).length,
  disabled: users.value.filter(u => !u.is_active).length
}))

// 过滤后的用户
const filteredUsers = computed(() => {
  let result = users.value
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    result = result.filter(u =>
      u.username?.toLowerCase().includes(kw) ||
      u.email?.toLowerCase().includes(kw)
    )
  }
  if (filterStatus.value !== '') {
    result = result.filter(u => u.is_active === filterStatus.value)
  }
  return result
})

const filterUsers = () => {
  // computed 自动响应，这里只是为了触发
}

// 加载用户列表
const loadUsers = async () => {
  loading.value = true
  try {
    const response = await authApi.listUsers()
    if (response.success) {
      users.value = response.data.users || []
    } else {
      ElMessage.error(response.message || '获取用户列表失败')
    }
  } catch (error: any) {
    console.error('获取用户列表失败:', error)
    ElMessage.error(error.message || '获取用户列表失败')
  } finally {
    loading.value = false
  }
}

// ==================== 创建用户 ====================
const showCreateDialog = ref(false)
const createLoading = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({
  username: '',
  email: '',
  password: '',
  is_admin: false
})

const createRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度必须在3-50个字符之间', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ]
}

const handleCreateUser = async () => {
  try {
    await createFormRef.value?.validate()
    createLoading.value = true

    const response = await authApi.createUser({
      username: createForm.username,
      email: createForm.email,
      password: createForm.password,
      is_admin: createForm.is_admin
    })

    if (response.success) {
      ElMessage.success(`用户 ${createForm.username} 创建成功`)
      showCreateDialog.value = false
      // 重置表单
      createForm.username = ''
      createForm.email = ''
      createForm.password = ''
      createForm.is_admin = false
      // 重新加载列表
      await loadUsers()
    } else {
      ElMessage.error(response.message || '创建失败')
    }
  } catch (error: any) {
    if (error.message && !error.message.includes('validate')) {
      ElMessage.error(error.message || '创建失败')
    }
  } finally {
    createLoading.value = false
  }
}

// ==================== 编辑用户 ====================
const showEditDialog = ref(false)
const editLoading = ref(false)
const editForm = reactive({
  username: '',
  email: '',
  daily_quota: 1000,
  concurrent_limit: 3,
  is_admin: false
})

const openEditDialog = (row: any) => {
  editForm.username = row.username
  editForm.email = row.email
  editForm.daily_quota = row.daily_quota || 1000
  editForm.concurrent_limit = row.concurrent_limit || 3
  editForm.is_admin = row.is_admin || false
  showEditDialog.value = true
}

const handleEditUser = async () => {
  editLoading.value = true
  try {
    const response = await authApi.updateUserStatus(editForm.username, {
      daily_quota: editForm.daily_quota,
      concurrent_limit: editForm.concurrent_limit,
      is_admin: editForm.is_admin
    })

    if (response.success) {
      ElMessage.success(`用户 ${editForm.username} 更新成功`)
      showEditDialog.value = false
      await loadUsers()
    } else {
      ElMessage.error(response.message || '更新失败')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '更新失败')
  } finally {
    editLoading.value = false
  }
}

// ==================== 激活/禁用用户 ====================
const toggleUserStatus = async (row: any) => {
  try {
    const action = row.is_active ? '禁用' : '激活'
    await ElMessageBox.confirm(
      `确定要${action}用户 "${row.username}" 吗？`,
      `${action}用户`,
      { type: 'warning' }
    )

    const response = await authApi.updateUserStatus(row.username, {
      is_active: !row.is_active
    })

    if (response.success) {
      ElMessage.success(`用户 ${row.username} 已${action}`)
      await loadUsers()
    } else {
      ElMessage.error(response.message || `${action}失败`)
    }
  } catch (error: any) {
    if (error !== 'cancel' && error?.message !== 'cancel') {
      ElMessage.error(error.message || '操作失败')
    }
  }
}

// ==================== 重置密码 ====================
const showResetPasswordDialog = ref(false)
const resetPasswordLoading = ref(false)
const resetPasswordFormRef = ref<FormInstance>()
const resetPasswordForm = reactive({
  username: '',
  new_password: '',
  confirm_password: ''
})

const resetPasswordRules: FormRules = {
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于6位', trigger: 'blur' }
  ],
  confirm_password: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== resetPasswordForm.new_password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

const openResetPasswordDialog = (row: any) => {
  resetPasswordForm.username = row.username
  resetPasswordForm.new_password = ''
  resetPasswordForm.confirm_password = ''
  showResetPasswordDialog.value = true
}

const handleResetPassword = async () => {
  try {
    await resetPasswordFormRef.value?.validate()
    resetPasswordLoading.value = true

    const response = await authApi.adminResetPassword(
      resetPasswordForm.username,
      resetPasswordForm.new_password
    )

    if (response.success) {
      ElMessage.success(`用户 ${resetPasswordForm.username} 的密码已重置`)
      showResetPasswordDialog.value = false
    } else {
      ElMessage.error(response.message || '重置失败')
    }
  } catch (error: any) {
    if (error.message && !error.message.includes('validate')) {
      ElMessage.error(error.message || '重置失败')
    }
  } finally {
    resetPasswordLoading.value = false
  }
}

// ==================== 删除用户 ====================
const confirmDeleteUser = async (row: any) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除用户 "${row.username}" 吗？此操作不可恢复！`,
      '删除用户',
      { type: 'error', confirmButtonText: '删除', cancelButtonText: '取消' }
    )

    const response = await authApi.deleteUser(row.username)

    if (response.success) {
      ElMessage.success(`用户 ${row.username} 已删除`)
      await loadUsers()
    } else {
      ElMessage.error(response.message || '删除失败')
    }
  } catch (error: any) {
    if (error !== 'cancel' && error?.message !== 'cancel') {
      ElMessage.error(error.message || '删除失败')
    }
  }
}

// ==================== 工具函数 ====================
const formatDateTime = (dateStr: string) => {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateStr
  }
}

// 初始化
onMounted(() => {
  loadUsers()
})
</script>

<style lang="scss" scoped>
.user-management {
  padding: 20px;

  .page-header {
    margin-bottom: 20px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      margin: 0 0 8px 0;

      .el-icon {
        font-size: 28px;
        color: var(--el-color-primary);
      }
    }

    .page-description {
      color: var(--el-text-color-secondary);
      font-size: 14px;
      margin: 0;
    }
  }

  .stats-row {
    margin-bottom: 16px;

    .stat-card {
      .stat-content {
        text-align: center;
        padding: 8px 0;

        .stat-value {
          font-size: 32px;
          font-weight: 700;
          color: var(--el-text-color-primary);

          &.stat-active {
            color: var(--el-color-success);
          }
          &.stat-admin {
            color: var(--el-color-danger);
          }
          &.stat-disabled {
            color: var(--el-text-color-placeholder);
          }
        }

        .stat-label {
          font-size: 14px;
          color: var(--el-text-color-secondary);
          margin-top: 4px;
        }
      }
    }
  }

  .toolbar {
    margin-bottom: 16px;

    .toolbar-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .toolbar-left {
      display: flex;
      align-items: center;
    }

    .toolbar-right {
      display: flex;
      gap: 10px;
    }
  }

  .user-cell {
    display: flex;
    align-items: center;
    gap: 8px;

    .username {
      font-weight: 500;
    }
  }

  .form-hint {
    margin-left: 12px;
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }
}
</style>

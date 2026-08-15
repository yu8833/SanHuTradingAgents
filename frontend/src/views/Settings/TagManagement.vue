<template>
  <div class="tag-management-page">
    <el-card shadow="never">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span>标签管理</span>
          <el-button type="primary" @click="openCreate">新建标签</el-button>
        </div>
      </template>
      <el-table :data="tags" v-loading="loading" style="width: 100%" empty-text="暂无标签">
        <el-table-column label="标签名" prop="name" width="200">
          <template #default="{ row }">
            <el-tag :color="row.color" effect="dark" size="small">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="颜色" prop="color" width="120">
          <template #default="{ row }">
            <div style="display: flex; align-items: center; gap: 6px;">
              <div :style="{width: '16px', height: '16px', borderRadius: '3px', background: row.color, border: '1px solid #ddd'}"></div>
              <span style="font-size: 12px;">{{ row.color }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="排序" prop="sort_order" width="80" />
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button text type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑标签' : '新建标签'" width="400px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标签名">
          <el-input v-model="form.name" placeholder="输入标签名称" />
        </el-form-item>
        <el-form-item label="颜色">
          <el-color-picker v-model="form.color" />
          <span style="margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary);">{{ form.color }}</span>
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" :max="999" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { tagsApi, type TagItem } from '@/api/tags'

defineOptions({ name: 'TagManagement' })

const tags = ref<TagItem[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref('')
const form = ref({ name: '', color: '#2b6cb0', sort_order: 0 })

async function loadData() {
  loading.value = true
  try {
    const res = await tagsApi.list()
    tags.value = (res as any)?.data || []
  } catch (e) {
    ElMessage.error('加载标签失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  form.value = { name: '', color: '#2b6cb0', sort_order: 0 }
  dialogVisible.value = true
}

function openEdit(row: TagItem) {
  editingId.value = row.id
  form.value = { name: row.name, color: row.color, sort_order: row.sort_order }
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.value.name) {
    ElMessage.warning('请输入标签名')
    return
  }
  try {
    if (editingId.value) {
      await tagsApi.update(editingId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await tagsApi.create(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

async function handleDelete(row: TagItem) {
  try {
    await ElMessageBox.confirm(`确定删除标签"${row.name}"吗？`, '提示', { type: 'warning' })
    await tagsApi.remove(row.id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) {
    // 取消删除
  }
}

function formatTime(time: string): string {
  if (!time) return '-'
  const d = new Date(time)
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')}`
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.tag-management-page { padding: 0; }
</style>
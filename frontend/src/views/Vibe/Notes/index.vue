<template>
  <div class="notes-page">
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">研究记录</h1>
        <p class="page-subtitle">AI 复盘/要点/问答沉淀，跨设备同步</p>
      </div>
      <div class="header-right">
        <el-button
          v-if="notes.length"
          type="danger"
          plain
          @click="confirmClear"
        >
          <el-icon><Delete /></el-icon>
          清空全部
        </el-button>
      </div>
    </div>

    <div v-loading="loading" class="notes-body">
      <template v-if="notes.length">
        <el-card
          v-for="note in notes"
          :key="note.id"
          class="note-card"
          shadow="never"
        >
          <div class="note-head" @click="toggle(note.id)">
            <el-icon class="toggle-icon">
              <CaretBottom v-if="expandedIds.has(note.id)" />
              <CaretRight v-else />
            </el-icon>
            <el-tag
              :type="kindTagType(note.kind)"
              size="small"
              effect="light"
              class="kind-tag"
            >
              {{ note.kind || '其他' }}
            </el-tag>
            <span class="note-title">{{ note.title || '无标题' }}</span>
            <span class="note-time">{{ formatTime(note.ts) }}</span>
            <el-icon
              class="delete-icon"
              @click.stop="confirmDelete(note.id)"
            >
              <Delete />
            </el-icon>
          </div>

          <div
            v-if="expandedIds.has(note.id)"
            class="note-content"
            v-html="renderContent(note.content)"
          ></div>
        </el-card>
      </template>

      <el-empty
        v-else-if="!loading"
        description="还没有记录"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, CaretBottom, CaretRight } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import { vibeApi } from '@/api/vibe'
import type { Note } from '@/api/vibe'

marked.setOptions({ breaks: true, gfm: true })

const loading = ref(false)
const notes = ref<Note[]>([])
const expandedIds = ref<Set<string>>(new Set())

const kindTagType = (kind: string): 'warning' | 'success' | 'info' => {
  if (kind === '复盘' || kind === '今日要点') return 'warning'
  if (kind === '问AI') return 'success'
  return 'info'
}

const formatTime = (ts: number): string => {
  if (!ts) return ''
  const d = new Date(ts)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

const renderContent = (content: string): string => {
  if (!content) return ''
  try {
    return sanitizeHtml(String(marked.parse(content)))
  } catch {
    return sanitizeHtml(content.replace(/\n/g, '<br/>'))
  }
}

const toggle = (id: string) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  expandedIds.value = next
}

const loadNotes = async () => {
  loading.value = true
  try {
    const list = await vibeApi.loadNotes()
    notes.value = (list || []).slice().sort((a, b) => b.ts - a.ts)
  } catch (e: any) {
    console.error('加载记录失败:', e)
    ElMessage.error(e?.message || '加载记录失败')
  } finally {
    loading.value = false
  }
}

const confirmDelete = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定删除这条记录？', '删除记录', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await vibeApi.deleteNote(id)
    await loadNotes()
    const next = new Set(expandedIds.value)
    next.delete(id)
    expandedIds.value = next
    ElMessage.success('已删除')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '删除失败')
  }
}

const confirmClear = async () => {
  try {
    await ElMessageBox.confirm(
      '将清空全部研究记录，且不可恢复，确定继续？',
      '清空记录',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await vibeApi.clearNotes()
    notes.value = []
    expandedIds.value = new Set()
    ElMessage.success('已清空')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.message || '清空失败')
  }
}

onMounted(() => {
  loadNotes()
})
</script>

<style lang="scss" scoped>
.notes-page {
  .page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 20px;

    .header-left {
      .page-title {
        font-size: 24px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        margin: 0 0 6px 0;
      }

      .page-subtitle {
        font-size: 14px;
        color: var(--el-text-color-secondary);
        margin: 0;
      }
    }
  }

  .notes-body {
    min-height: 200px;
  }

  .note-card {
    margin-bottom: 12px;
    border-radius: 8px;

    :deep(.el-card__body) {
      padding: 12px 16px;
    }

    .note-head {
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      user-select: none;

      .toggle-icon {
        color: var(--el-text-color-secondary);
        font-size: 14px;
        flex-shrink: 0;
      }

      .kind-tag {
        flex-shrink: 0;
      }

      .note-title {
        flex: 1;
        font-size: 14px;
        font-weight: 500;
        color: var(--el-text-color-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .note-time {
        font-size: 12px;
        color: var(--el-text-color-placeholder);
        flex-shrink: 0;
      }

      .delete-icon {
        color: var(--el-text-color-placeholder);
        font-size: 14px;
        flex-shrink: 0;
        cursor: pointer;
        transition: color 0.2s;

        &:hover {
          color: var(--el-color-danger);
        }
      }
    }

    .note-content {
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--el-border-color-lighter);
      font-size: 14px;
      line-height: 1.7;
      color: var(--el-text-color-regular);
      word-break: break-word;

      :deep(h1),
      :deep(h2),
      :deep(h3),
      :deep(h4) {
        margin: 10px 0 6px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      :deep(p) {
        margin: 4px 0;
      }

      :deep(ul),
      :deep(ol) {
        padding-left: 20px;
        margin: 4px 0;
      }

      :deep(code) {
        background: var(--el-fill-color-light);
        padding: 2px 4px;
        border-radius: 4px;
        font-size: 13px;
      }

      :deep(pre) {
        background: var(--el-fill-color-light);
        padding: 10px 12px;
        border-radius: 6px;
        overflow-x: auto;
      }
    }
  }
}
</style>

<template>
  <div class="sectors-page">
    <div class="page-header">
      <h1 class="page-title">全部板块</h1>
      <p class="page-subtitle">热门赛道的产业链骨架</p>
    </div>

    <div v-loading="loading" class="sectors-body">
      <el-row v-if="sectors.length" :gutter="16">
        <el-col
          v-for="sector in sectors"
          :key="sector.key"
          :xs="24"
          :sm="12"
          :md="8"
        >
          <el-card
            class="sector-card"
            shadow="hover"
            @click="goDetail(sector.key)"
          >
            <div class="card-head">
              <span class="sector-name">{{ sector.label }}</span>
              <el-tag
                v-if="sector.hot"
                type="danger"
                size="small"
                effect="dark"
                class="hot-tag"
              >
                <el-icon class="hot-icon"><Lightning /></el-icon>
                热门
              </el-tag>
            </div>

            <p class="sector-tagline">{{ sector.tagline || '—' }}</p>

            <div class="card-foot">
              <template v-if="sector.verified">
                <span class="foot-verified">
                  {{ sector.nodes.length }} 个环节
                </span>
                <el-icon class="foot-arrow"><ArrowRight /></el-icon>
              </template>
              <template v-else>
                <span class="foot-pending">环节梳理中</span>
                <el-icon class="foot-arrow pending"><ArrowRight /></el-icon>
              </template>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-empty
        v-else-if="!loading"
        description="暂无板块数据"
      />
    </div>

    <p class="disclaimer">
      只有环节，不含标的。用户可在本地挂自己的标的。
    </p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lightning, ArrowRight } from '@element-plus/icons-vue'
import { vibeApi } from '@/api/vibe'
import type { SectorNode } from '@/api/vibe'

const router = useRouter()

const loading = ref(false)
const sectors = ref<SectorNode[]>([])

const loadSectors = async () => {
  loading.value = true
  try {
    const res = await vibeApi.getSectors()
    sectors.value = res?.data?.sectors || []
  } catch (e: any) {
    console.error('加载板块失败:', e)
    ElMessage.error(e?.message || '加载板块失败')
  } finally {
    loading.value = false
  }
}

const goDetail = (key: string) => {
  router.push(`/vibe/sectors/${key}`)
}

onMounted(() => {
  loadSectors()
})
</script>

<style lang="scss" scoped>
.sectors-page {
  .page-header {
    margin-bottom: 24px;

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

  .sectors-body {
    min-height: 200px;
  }

  .sector-card {
    margin-bottom: 16px;
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    border-radius: 8px;

    &:hover {
      transform: translateY(-2px);
    }

    :deep(.el-card__body) {
      padding: 16px 18px;
    }

    .card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;

      .sector-name {
        font-size: 16px;
        font-weight: 600;
        color: var(--el-text-color-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .hot-tag {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        flex-shrink: 0;

        .hot-icon {
          font-size: 12px;
        }
      }
    }

    .sector-tagline {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin: 0 0 14px 0;
      line-height: 1.5;
      min-height: 20px;
    }

    .card-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 13px;
      color: var(--el-text-color-regular);

      .foot-verified {
        color: var(--el-color-primary);
      }

      .foot-pending {
        color: var(--el-text-color-placeholder);
      }

      .foot-arrow {
        color: var(--el-text-color-placeholder);

        &.pending {
          opacity: 0.6;
        }
      }
    }
  }

  .disclaimer {
    margin-top: 24px;
    font-size: 12px;
    color: var(--el-text-color-placeholder);
    line-height: 1.6;
  }
}
</style>

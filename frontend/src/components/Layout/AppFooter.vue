<template>
  <div class="app-footer">
    <div class="footer-content">
      <p class="copyright">© 2026 股票分析系统. All rights reserved.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
</script>

<style lang="scss" scoped>
.app-footer {
  .footer-content {
    display: flex;
    justify-content: center;
    align-items: center;
    color: var(--el-text-color-secondary);
    font-size: 14px;
    padding: 12px 16px;
    text-align: center;
  }

  .copyright {
    margin: 0;
  }
}
</style>

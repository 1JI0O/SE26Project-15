<template>
  <div class="app-shell">
    <header class="topbar">
      <router-link class="brand" to="/">
        <span class="brand-mark">T</span>
        <span>
          <strong>论文代码双向追溯 Web 工作台</strong>
          <small>Iteration 1 Prototype</small>
        </span>
      </router-link>
      <el-tag effect="plain" type="success">接口先行</el-tag>
    </header>
    <main class="workspace">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: #f6f8fa;
  color: #24313d;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 64px;
  padding: 0 28px;
  border-bottom: 1px solid #dce3ea;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(10px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: inherit;
  text-decoration: none;
}

.brand small {
  display: block;
  margin-top: 2px;
  color: #71808f;
  font-size: 12px;
}

.brand-mark {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 8px;
  background: #1f8f78;
  color: white;
  font-weight: 700;
}

.workspace {
  width: min(1440px, calc(100% - 40px));
  margin: 0 auto;
  padding: 24px 0 40px;
}

@media (max-width: 720px) {
  .topbar {
    height: auto;
    padding: 12px 16px;
    align-items: flex-start;
  }

  .workspace {
    width: min(100% - 24px, 1440px);
    padding-top: 16px;
  }
}
</style>


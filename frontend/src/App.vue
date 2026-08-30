<template>
  <div class="app">
    <header class="app-header">
      <h1>选基助手</h1>
      <nav class="nav-links">
        <router-link to="/" class="nav-link">首页</router-link>
        <router-link to="/qdii" class="nav-link">QDII额度</router-link>
        <router-link to="/fund-eval" class="nav-link">基金评测</router-link>
        <router-link to="/etf-momentum" class="nav-link">ETF轮动</router-link>
        <router-link to="/industry" class="nav-link">行业基金</router-link>
        <router-link to="/backtest" class="nav-link">策略回测</router-link>
      </nav>
    </header>

    <main class="page-container">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
</script>

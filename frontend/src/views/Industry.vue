<template>
  <div class="industry-page">
    <div class="dashboard-card">
      <div class="section-header">
        <h2 class="section-title">A股行业板块监测</h2>
        <el-button type="primary" @click="manualRefresh" :loading="refreshing">
          <el-icon><Refresh /></el-icon>
          更新数据
        </el-button>
      </div>

      <el-tabs v-model="activeTab" class="industry-tabs">
        <el-tab-pane label="全部" name="all">
          <span class="tab-label">全部 <el-tag size="small">{{ ranking.length }}</el-tag></span>
        </el-tab-pane>
        <el-tab-pane :label="`行业指数 (${rankingBySource.index})`" name="index">
          <span class="tab-label">行业指数 <el-tag type="success" size="small">{{ rankingBySource.index }}</el-tag></span>
        </el-tab-pane>
        <el-tab-pane :label="`ETF代理 (${rankingBySource.etf})`" name="etf">
          <span class="tab-label">ETF代理 <el-tag type="info" size="small">{{ rankingBySource.etf }}</el-tag></span>
        </el-tab-pane>
      </el-tabs>

      <!-- 行业涨跌幅排行榜 -->
      <el-row :gutter="16">
        <el-col :span="16">
          <div class="ranking-card">
            <h3>📊 行业涨跌幅排名（{{ activeTab === 'all' ? '全部' : activeTab === 'index' ? '行业指数' : 'ETF代理' }}）</h3>
            <el-table :data="filteredRanking" stripe size="small">
              <el-table-column type="index" label="排名" width="60" />
              <el-table-column prop="industry" label="行业" width="100">
                <template #default="{ row }">
                  <strong>{{ row.industry }}</strong>
                </template>
              </el-table-column>
              <el-table-column label="来源" width="90">
                <template #default="{ row }">
                  <el-tag
                    :type="row.data_source === 'index' ? 'success' : 'info'"
                    size="small"
                    effect="plain"
                  >
                    {{ row.data_source === 'index' ? '行业指数' : 'ETF代理' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" sortable width="100">
                <template #default="{ row }">
                  <span :class="getChangeClass(row.change_pct)">
                    {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="signal" label="信号" width="80">
                <template #default="{ row }">
                  <el-tag :type="getSignalType(row.signal)" size="small">
                    {{ row.signal }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="代表性ETF" min-width="200">
                <template #default="{ row }">
                  <div v-if="row.funds && row.funds.length">
                    <span
                      v-for="(fund) in row.funds.slice(0, 2)"
                      :key="fund.code"
                      class="etf-tag"
                    >
                      {{ fund.name.replace(/[^一-龥]/g, '').slice(0, 6) }}
                      <span :class="getChangeClass(fund.change_pct)">
                        {{ fund.change_pct >= 0 ? '+' : '' }}{{ fund.change_pct }}%
                      </span>
                    </span>
                  </div>
                  <span v-else class="text-muted">暂无数据</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-col>

        <el-col :span="8">
          <div class="heat-card">
            <h3>🔥 行业热度（指数源）</h3>
            <div class="heat-list">
              <div
                v-for="item in (rankingBySource.index ? indexOnlyRanking.slice(0, 6) : ranking.slice(0, 6))"
                :key="item.industry"
                class="heat-item"
                :style="{ backgroundColor: getHeatColor(item.change_pct) }"
              >
                <span class="heat-name">{{ item.industry }}</span>
                <span class="heat-value">
                  {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct }}%
                </span>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-divider />

      <!-- 弱势板块 -->
      <div class="weak-industries" v-if="weakIndustries.length">
        <h3>📉 弱势板块（跌幅 > 2%）</h3>
        <el-row :gutter="12">
          <el-col :span="6" v-for="item in weakIndustries" :key="item.industry + item.data_source">
            <div class="weak-card">
              <div class="weak-name">{{ item.industry }}</div>
              <div :class="getChangeClass(item.change_pct)">
                {{ item.change_pct >= 0 ? '+' : '' }}{{ item.change_pct }}%
              </div>
            </div>
          </el-col>
        </el-row>
      </div>

      <div class="info-tip">
        <el-icon><InfoFilled /></el-icon>
        <span>
          数据来源：腾讯 qt.gtimg.cn（行业指数，覆盖32个行业板块） + 新浪 hq.sinajs.cn（ETF代理，45个细分行业） | 更新时间：{{ updateTime }}
          <br>
          行业指数是更全面的板块基准（涵盖全行业个股），ETF代理反映场内细分行业的实时走势
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { industryApi } from '@/api'

const ranking = ref<any[]>([])
const loading = ref(false)
const refreshing = ref(false)
const updateTime = ref('')
const activeTab = ref('all')

const rankingBySource = computed(() => {
  const counts = { index: 0, etf: 0 }
  for (const r of ranking.value) {
    if (r.data_source === 'index') counts.index++
    else if (r.data_source === 'etf') counts.etf++
  }
  return counts
})

const indexOnlyRanking = computed(() => {
  return ranking.value.filter(r => r.data_source === 'index')
})

const filteredRanking = computed(() => {
  if (activeTab.value === 'all') return ranking.value
  return ranking.value.filter(r => r.data_source === activeTab.value)
})

const weakIndustries = computed(() => {
  return filteredRanking.value.filter(r => r.change_pct < -2)
})

const getChangeClass = (pct: number) => {
  if (pct > 0) return 'status-red'
  if (pct < 0) return 'status-green'
  return ''
}

const getSignalType = (signal: string) => {
  switch (signal) {
    case '强势': return 'success'
    case '偏强': return 'warning'
    case '偏弱': return 'warning'
    case '弱势': return 'danger'
    default: return 'info'
  }
}

const getHeatColor = (pct: number) => {
  const intensity = Math.min(Math.abs(pct) / 5, 1)
  if (pct > 0) {
    return `rgba(245, 108, 108, ${intensity * 0.8})`
  } else {
    return `rgba(103, 194, 58, ${intensity * 0.8})`
  }
}

const loadRanking = async () => {
  loading.value = true
  try {
    const res = await industryApi.getRanking()
    ranking.value = res.data.ranking || []
    updateTime.value = res.data.update_time?.slice(0, 19) || ''
  } catch (error) {
    console.error('加载失败:', error)
  } finally {
    loading.value = false
  }
}

const manualRefresh = async () => {
  refreshing.value = true
  try {
    await industryApi.refreshRanking()
    await loadRanking()
  } catch (error) {
    console.error('更新失败:', error)
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  loadRanking()
})
</script>

<style scoped>
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.ranking-card, .heat-card {
  padding: 16px;
  background: #f9f9f9;
  border-radius: 8px;
}

.ranking-card h3, .heat-card h3 {
  margin-bottom: 16px;
  font-size: 14px;
  color: #606266;
}

.heat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.heat-item {
  display: flex;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 6px;
  color: white;
  font-weight: 500;
}

.heat-name {
  font-size: 14px;
}

.heat-value {
  font-size: 16px;
  font-weight: bold;
}

.etf-tag {
  display: inline-block;
  margin-right: 12px;
  font-size: 12px;
  color: #909399;
}

.weak-industries h3 {
  color: #606266;
  margin-bottom: 16px;
}

.weak-card {
  background: #fef0f0;
  border-radius: 6px;
  padding: 12px;
  text-align: center;
}

.weak-name {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}

.weak-card .status-green {
  font-size: 18px;
  font-weight: bold;
}

.info-tip {
  margin-top: 20px;
  padding: 12px;
  background: #f4f4f5;
  border-radius: 4px;
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.text-muted {
  color: #c0c4cc;
}

.industry-tabs {
  margin-bottom: 16px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>

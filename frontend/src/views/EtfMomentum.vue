<template>
  <div class="etf-momentum-page">
    <div class="dashboard-card">
      <div class="section-header">
        <h2 class="section-title">ETF 双动量轮动策略</h2>
        <div class="header-actions">
          <el-radio-group v-model="strategy" @change="loadData">
            <el-radio-button label="aggressive">激进型</el-radio-button>
            <el-radio-button label="conservative">保守型</el-radio-button>
          </el-radio-group>
          <el-button @click="poolDrawerOpen = true" plain>
            <el-icon><Setting /></el-icon>
            标的池管理
          </el-button>
          <el-button type="primary" @click="manualRefresh" :loading="loading">
            <el-icon><Refresh /></el-icon>
            更新数据
          </el-button>
        </div>
      </div>

      <!-- ETF 标的池管理抽屉 -->
      <el-drawer v-model="poolDrawerOpen" title="ETF 标的池管理" direction="rtl" size="500px">
        <div class="pool-drawer-content">
          <el-table :data="poolList" stripe>
            <el-table-column prop="code" label="代码" width="100" />
            <el-table-column prop="name" label="名称" width="160" />
            <el-table-column prop="short_name" label="短名" width="80" />
            <el-table-column prop="type" label="类型" width="90" />
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }">
                <el-button v-if="row.is_active" type="danger" size="small" link @click="removePool(row)">
                  删除
                </el-button>
                <el-tag v-else size="small" type="info">已停用</el-tag>
              </template>
            </el-table-column>
          </el-table>

          <el-divider>新增 ETF</el-divider>
          <el-form :model="newPoolItem" label-width="80px" size="default">
            <el-form-item label="代码">
              <el-input v-model="newPoolItem.code" placeholder="如 159915" />
            </el-form-item>
            <el-form-item label="名称">
              <el-input v-model="newPoolItem.name" placeholder="如 创业板ETF" />
            </el-form-item>
            <el-form-item label="短名">
              <el-input v-model="newPoolItem.short_name" placeholder="≤3 字，飞书推送显示" />
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="newPoolItem.type" placeholder="选择类型" style="width: 100%">
                <el-option label="国内" value="国内" />
                <el-option label="红利" value="红利" />
                <el-option label="美股" value="美股" />
                <el-option label="黄金" value="黄金" />
                <el-option label="债券" value="债券" />
                <el-option label="商品" value="商品" />
                <el-option label="其他" value="其他" />
              </el-select>
            </el-form-item>
            <el-form-item label="排序">
              <el-input-number v-model="newPoolItem.sort_order" :min="0" :max="999" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="addPool" :loading="poolSaving">添加</el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-drawer>

      <!-- 持仓建议 -->
      <div class="holding-recommendation">
        <div class="recommendation-header">
          <span class="recommendation-label">📌 当前建议</span>
          <el-tag v-if="signal" :type="recommendationType" size="large">
            {{ signal }}
          </el-tag>
        </div>
        <div v-if="holdings.length && topEtf" class="top-etf-card">
          <div class="top-etf-info">
            <div class="top-etf-name">{{ topEtf.name }}</div>
            <div class="top-etf-detail">
              <span>今日涨跌: <span :class="getChangeClass(topEtf.daily_change)">{{ topEtf.daily_change }}%</span></span>
              <span>综合评分: <span class="score">{{ topEtf.combined_score }}</span></span>
              <span>短期动量: <span :class="getMomentumClass(topEtf.short_momentum)">{{ topEtf.short_momentum }}%</span></span>
              <span>60日线上方: <span :class="getAboveMa60Class(topEtf.above_ma60)">{{ topEtf.above_ma60 }}</span></span>
              <span>连续第1: <span class="score">{{ topEtf.consecutive_rank1_days || 0 }} 天</span></span>
            </div>
          </div>
          <div class="rank-badge">🥇 排名第1</div>
        </div>
        <div v-else-if="signal && signal.includes('观望')" class="no-position">
          <el-icon size="24"><WarningFilled /></el-icon>
          <span>{{ signal }}</span>
        </div>
        <div v-if="switchSuggestion" class="switch-suggestion">
          {{ switchSuggestion }}
        </div>
      </div>

      <!-- 候选 ETF 动量排名 -->
      <div class="candidates-card">
        <h3>动量排名</h3>
        <el-table :data="candidates" stripe>
          <el-table-column label="排名" width="70">
            <template #default="{ $index }">
              <span :class="getRankClass($index + 1)">
                {{ $index + 1 === 1 ? '🥇' : ($index + 1 === 2 ? '🥈' : ($index + 1 === 3 ? '🥉' : `#${$index + 1}`)) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column prop="code" label="代码" width="100" />
          <el-table-column prop="daily_change" label="今日涨跌" width="100" sortable>
            <template #default="{ row }">
              <span :class="getChangeClass(row.daily_change)">
                {{ row.daily_change }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="short_momentum" label="短期(20日)" width="100" sortable>
            <template #default="{ row }">
              <span :class="getMomentumClass(row.short_momentum)">
                {{ row.short_momentum }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="above_ma60" label="60日线上方" width="110" sortable>
            <template #default="{ row }">
              <span :class="getAboveMa60Class(row.above_ma60)">
                {{ row.above_ma60 }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="consecutive_rank1_days" label="连续第1天数" width="120" sortable>
            <template #default="{ row }">
              <el-tag :type="(row.consecutive_rank1_days || 0) >= 3 ? 'success' : 'info'" size="small">
                {{ row.consecutive_rank1_days || 0 }} 天
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="combined_score" label="综合评分" width="100" sortable>
            <template #default="{ row }">
              <span :class="getScoreClass(row.combined_score)">
                {{ row.combined_score }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="signal" label="信号" width="80">
            <template #default="{ row }">
              <el-tag :type="getSignalType(row.signal)" size="small">{{ getSignalText(row.signal) }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="strategy-info">
        <el-icon><InfoFilled /></el-icon>
        <div>
          <strong>双动量策略说明：</strong><br>
          - 连续 N 天动量排名第一才推荐买入（连续天数 ≤ 1 时仅按当日排名推荐）<br>
          - 价格需站在60日线上方才参与排名（趋势过滤）<br>
          - 激进型：综合评分 = 100% 短期涨幅 (20日)，买入阈值 > 3<br>
          - 保守型：综合评分 = 20日夏普比率 (mean/std × √252)，买入阈值 > 0<br>
          <span v-if="updateTime">- 数据更新于: {{ updateTime }}</span>
        </div>
      </div>

      <!-- 数据源对比 -->
      <div v-if="sourceCompare.length" class="compare-card">
        <h3>数据源交叉验证（新浪 vs 腾讯）</h3>
        <el-table :data="sourceCompare" stripe size="small">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column label="20日涨幅" align="right">
            <template #default="{ row }">
              <div class="compare-cell">
                <span>新浪: {{ row.sina.short_momentum }}%</span>
                <span>腾讯: {{ row.tencent.short_momentum }}%</span>
                <span :class="getDiffClass(row.diff.short_momentum)">差: {{ formatDiff(row.diff.short_momentum) }}%</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="60日线上方" align="right">
            <template #default="{ row }">
              <div class="compare-cell">
                <span>新浪: {{ row.sina.above_ma60 }}</span>
                <span>腾讯: {{ row.tencent.above_ma60 }}</span>
                <span :class="row.sina.above_ma60 === row.tencent.above_ma60 ? 'text-success' : 'text-danger'">一致: {{ row.sina.above_ma60 === row.tencent.above_ma60 ? '✓' : '✗' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="20日夏普" align="right">
            <template #default="{ row }">
              <div class="compare-cell">
                <span>新浪: {{ row.sina.short_sharpe }}</span>
                <span>腾讯: {{ row.tencent.short_sharpe }}</span>
                <span :class="getDiffClass(row.diff.short_sharpe)">差: {{ formatDiff(row.diff.short_sharpe) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="信号" align="center">
            <template #default="{ row }">
              <div class="compare-cell">
                <span>新浪: <el-tag :type="getSignalType(row.sina.signal)" size="small">{{ getSignalText(row.sina.signal) }}</el-tag></span>
                <span>腾讯: <el-tag :type="getSignalType(row.tencent.signal)" size="small">{{ getSignalText(row.tencent.signal) }}</el-tag></span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="一致" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.consistent ? 'success' : 'danger'" size="small">
                {{ row.consistent ? '✓' : '✗' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { WarningFilled, InfoFilled, Refresh, Setting } from '@element-plus/icons-vue'
import { etfApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const strategy = ref('aggressive')
const holdings = ref<any[]>([])
const candidates = ref<any[]>([])
const signal = ref('')
const switchSuggestion = ref('')
const updateTime = ref('')
const loading = ref(false)

const sourceCompare = ref<any[]>([])

// 标的池管理
const poolDrawerOpen = ref(false)
const poolList = ref<any[]>([])
const poolSaving = ref(false)
const newPoolItem = ref({ code: '', name: '', short_name: '', type: '其他', sort_order: 0 })

const topEtf = computed(() => candidates.value[0] || null)

const getDiffClass = (v: number) => {
  if (Math.abs(v) >= 0.1) return 'text-danger'
  if (Math.abs(v) >= 0.01) return 'text-warning'
  return 'text-success'
}

const formatDiff = (v: number) => (v > 0 ? '+' : '') + v.toFixed(2)

const recommendationType = computed(() => {
  if (signal.value.includes('观望')) return 'warning'
  if (signal.value.includes('继续持有')) return 'success'
  return 'primary'
})

const getRankClass = (rank: number) => {
  if (rank === 1) return 'rank-gold'
  if (rank === 2) return 'rank-silver'
  if (rank === 3) return 'rank-bronze'
  return ''
}

const getChangeClass = (value: number) => {
  if (value > 0) return 'change-up'
  if (value < 0) return 'change-down'
  return ''
}

const getMomentumClass = (value: number) => {
  if (value > 10) return 'status-green'
  if (value > 0) return 'status-yellow'
  return 'status-red'
}

const getAboveMa60Class = (value: boolean) => {
  return value ? 'status-green' : 'status-red'
}

const getScoreClass = (score: number) => {
  if (score > 8) return 'signal-buy'
  if (score > 0) return 'signal-hold'
  return 'signal-sell'
}

const getSignalType = (signal: string) => {
  switch (signal) {
    case 'buy': return 'success'
    case 'hold': return 'warning'
    case 'sell': return 'danger'
    default: return 'info'
  }
}

const getSignalText = (signal: string) => {
  switch (signal) {
    case 'buy': return '买入'
    case 'hold': return '持有'
    case 'sell': return '卖出'
    default: return signal
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await etfApi.getMomentum(strategy.value)
    holdings.value = res.data.holdings || []
    candidates.value = res.data.candidates || []
    signal.value = res.data.signal || ''
    switchSuggestion.value = res.data.switch_suggestion || ''
    updateTime.value = res.data.last_update || ''
  } catch (error) {
    console.error('读取失败:', error)
  } finally {
    loading.value = false
  }
}

// 手动更新：触发后端计算并写入数据库
const manualRefresh = async () => {
  loading.value = true
  try {
    await etfApi.refreshMomentum()
    // 刷新后立即重读最新数据
    await loadData()
  } catch (error) {
    console.error('更新失败:', error)
  } finally {
    loading.value = false
  }
}

// ============ 标的池管理 ============

const loadPool = async () => {
  try {
    const res = await etfApi.getPool()
    poolList.value = res.data.pool || []
  } catch (error) {
    console.error('读取 ETF 池子失败:', error)
  }
}

const resetNewPoolItem = () => {
  newPoolItem.value = { code: '', name: '', short_name: '', type: '其他', sort_order: 0 }
}

const addPool = async () => {
  if (!newPoolItem.value.code || !newPoolItem.value.name) {
    ElMessage.warning('代码和名称必填')
    return
  }
  poolSaving.value = true
  try {
    await etfApi.addPoolItem({
      code: newPoolItem.value.code.trim(),
      name: newPoolItem.value.name.trim(),
      short_name: newPoolItem.value.short_name.trim() || undefined,
      type: newPoolItem.value.type,
      sort_order: newPoolItem.value.sort_order,
    })
    ElMessage.success('添加成功')
    resetNewPoolItem()
    await Promise.all([loadPool(), loadData()])
  } catch (error: any) {
    console.error('添加 ETF 失败:', error)
    ElMessage.error(error?.response?.data?.detail || '添加失败')
  } finally {
    poolSaving.value = false
  }
}

const removePool = async (row: any) => {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${row.name} (${row.code})？删除后将不再参与轮动排名。`,
      '删除 ETF',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  try {
    await etfApi.removePoolItem(row.code)
    ElMessage.success('已删除')
    await Promise.all([loadPool(), loadData()])
  } catch (error) {
    console.error('删除 ETF 失败:', error)
    ElMessage.error('删除失败')
  }
}

watch(poolDrawerOpen, (open) => {
  if (open) loadPool()
})

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.holding-recommendation {
  margin-bottom: 20px;
  padding: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  color: white;
}

.recommendation-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.recommendation-label {
  font-size: 16px;
  font-weight: bold;
}

.top-etf-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 8px;
}

.top-etf-name {
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 8px;
}

.top-etf-detail {
  display: flex;
  gap: 20px;
  font-size: 13px;
  opacity: 0.9;
}

.top-etf-detail .score {
  color: #ffd700;
  font-weight: bold;
}

.rank-badge {
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 14px;
}

.no-position {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 8px;
}

.switch-suggestion {
  margin-top: 12px;
  padding: 10px 16px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  font-size: 14px;
}

.candidates-card {
  padding: 16px;
  background: #f9f9f9;
  border-radius: 8px;
}

.candidates-card h3 {
  margin-bottom: 16px;
  font-size: 14px;
  color: #606266;
}

.rank-gold { color: #ffd700; font-weight: bold; }
.rank-silver { color: #c0c0c0; font-weight: bold; }
.rank-bronze { color: #cd7f32; font-weight: bold; }

.change-up { color: #f56c6c; font-weight: bold; }
.change-down { color: #67c23a; font-weight: bold; }
.status-green { color: #67c23a; }
.status-yellow { color: #e6a23c; }
.status-red { color: #f56c6c; }
.signal-buy { color: #67c23a; font-weight: bold; }
.signal-hold { color: #e6a23c; }
.signal-sell { color: #f56c6c; }

.strategy-info {
  margin-top: 20px;
  padding: 16px;
  background: #ecf5ff;
  border-radius: 8px;
  color: #409eff;
  font-size: 13px;
  display: flex;
  gap: 12px;
}

.strategy-info strong {
  color: #303133;
}
</style>

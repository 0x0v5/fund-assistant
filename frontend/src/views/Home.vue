<template>
  <div class="home">
    <!-- Hero -->
    <div class="hero">
      <div class="hero-content">
        <h1 class="hero-title">选基助手</h1>
        <p class="hero-subtitle">基金评测 · QDII 额度 · ETF 轮动 · 行业基金 · 历史回测</p>
      </div>
      <div class="hero-stats">
        <div class="hero-stat">
          <div class="hero-stat-value">{{ stats.qdii }}</div>
          <div class="hero-stat-label">QDII 基金</div>
        </div>
        <div class="hero-stat-divider"></div>
        <div class="hero-stat">
          <div class="hero-stat-value">{{ stats.etf }}</div>
          <div class="hero-stat-label">ETF 标的</div>
        </div>
        <div class="hero-stat-divider"></div>
        <div class="hero-stat">
          <div class="hero-stat-value">{{ stats.eval }}</div>
          <div class="hero-stat-label">已评测</div>
        </div>
        <div class="hero-stat-divider"></div>
        <div class="hero-stat">
          <div class="hero-stat-value">{{ stats.backtest }}</div>
          <div class="hero-stat-label">回测记录</div>
        </div>
      </div>
    </div>

    <!-- 4 张渐变色数据卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card card-gradient-purple" @click="$router.push('/qdii')">
          <div class="stat-icon"><el-icon :size="24"><TrendCharts /></el-icon></div>
          <div class="stat-label">QDII 额度</div>
          <div class="stat-value">{{ qdiiStatus }}</div>
          <div class="stat-desc">{{ qdiiCount }} 支基金监控中</div>
        </div>
      </el-col>

      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card card-gradient-pink" @click="$router.push('/etf-momentum')">
          <div class="stat-icon"><el-icon :size="24"><DataLine /></el-icon></div>
          <div class="stat-label">ETF 轮动</div>
          <div class="stat-value" :class="signalClass">{{ etfSignal }}</div>
          <div class="stat-desc">{{ etfTop ? `${etfTop} · 🥇第一` : '暂无信号' }}</div>
        </div>
      </el-col>

      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card card-gradient-blue" @click="$router.push('/industry')">
          <div class="stat-icon"><el-icon :size="24"><PieChart /></el-icon></div>
          <div class="stat-label">热门行业</div>
          <div class="stat-value">{{ hotIndustry }}</div>
          <div class="stat-desc" :class="indChangeClass">{{ indChangeStr }}</div>
        </div>
      </el-col>

      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card card-gradient-green">
          <div class="stat-icon"><el-icon :size="24"><Timer /></el-icon></div>
          <div class="stat-label">数据更新</div>
          <div class="stat-value" style="font-size: 18px">{{ lastUpdateLabel }}</div>
          <div class="stat-desc">{{ updateStatusLabel }}</div>
        </div>
      </el-col>
    </el-row>

    <!-- 主体双栏：左 快捷入口，右 最近操作 -->
    <el-row :gutter="20" class="main-row">
      <el-col :xs="24" :md="9">
        <div class="dashboard-card">
          <div class="card-section-title">快捷入口</div>
          <div class="quick-grid">
            <div
              v-for="(item) in quickEntries"
              :key="item.path"
              class="quick-tile"
              :style="{ background: item.gradient }"
              @click="$router.push(item.path)"
            >
              <el-icon :size="28"><component :is="item.icon" /></el-icon>
              <div class="quick-tile-label">{{ item.label }}</div>
              <div class="quick-tile-desc">{{ item.desc }}</div>
            </div>
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :md="15">
        <div class="dashboard-card">
          <div class="card-section-title">
            最近操作
            <el-button text type="primary" size="small" @click="loadActivity" :loading="loadingActivity" style="margin-left: 8px">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
          <el-skeleton v-if="loadingActivity && !activityList.length" :rows="6" animated />
          <el-empty v-else-if="!activityList.length" description="暂无最近操作" />
          <div v-else class="activity-list">
            <div
              v-for="(item, idx) in activityList"
              :key="idx"
              class="activity-item"
              :class="[`kind-${item.kind}`]"
              @click="goActivity(item)"
            >
              <div class="activity-dot"></div>
              <div class="activity-main">
                <div class="activity-title">{{ stripEmoji(item.title) }}</div>
                <div class="activity-summary">{{ item.summary }}</div>
              </div>
              <div class="activity-time">{{ item.time }}</div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  TrendCharts, DataLine, PieChart, Timer,
  Refresh, Position, Coin, Histogram, DataAnalysis,
} from '@element-plus/icons-vue'
import { qdiiApi, etfApi, industryApi, backtestApi, fundApi, activityApi } from '@/api'

const router = useRouter()

// 4 张 stat 卡（顶部）
const qdiiStatus = ref('--')
const qdiiCount = ref(0)
const etfSignal = ref('--')
const etfTop = ref('')
const holdingCount = ref(0)
const hotIndustry = ref('--')
const indChange = ref<number | null>(null)
const lastUpdateLabel = ref('--')
const updateStatusLabel = ref('加载中')

// 顶部 hero stat
const stats = ref({ qdii: 0, etf: 0, eval: 0, backtest: 0 })

// 最近活动
const activityList = ref<any[]>([])
const loadingActivity = ref(false)

// 快捷入口
const quickEntries = [
  { path: '/qdii', label: 'QDII 额度', desc: '实时限额监控', icon: Coin, gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' },
  { path: '/fund-eval', label: '基金评测', desc: '多维评分雷达', icon: DataAnalysis, gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' },
  { path: '/etf-momentum', label: 'ETF 轮动', desc: '双动量策略', icon: Position, gradient: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' },
  { path: '/industry', label: '行业基金', desc: '涨跌榜', icon: Histogram, gradient: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)' },
  { path: '/backtest', label: '回测对比', desc: '历史数据验证', icon: DataLine, gradient: 'linear-gradient(135deg, #fa709a 0%, #fee140 100%)' },
]

const signalClass = computed(() => {
  const s = etfSignal.value
  if (s === '买入' || s === '继续持有' || s === '持有') return 'text-success'
  if (s === '观望' || s === '建议观望') return 'text-warning'
  if (s === '建议切换' || s === '卖出') return 'text-danger'
  return ''
})

const indChangeClass = computed(() => {
  const v = indChange.value
  if (v == null) return ''
  return v >= 0 ? 'text-danger' : 'text-success'  // 中国股市惯例：正红负绿
})

const indChangeStr = computed(() => {
  const v = indChange.value
  if (v == null) return '动量排名 #1'
  return `动量排行 #1  ·  ${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
})

function stripEmoji(s: string) {
  return s.replace(/^[^一-龥A-Za-z0-9]+/, '')
}

function goActivity(item: any) {
  if (item.link) router.push(item.link)
}

async function loadActivity() {
  loadingActivity.value = true
  try {
    const res = await activityApi.getRecent(12)
    activityList.value = res.data.items || []
  } catch (err) {
    console.error('加载最近活动失败:', err)
  } finally {
    loadingActivity.value = false
  }
}

onMounted(async () => {
  // 并行拉所有数据
  const [qdiiR, etfR, indR, btR, favR] = await Promise.allSettled([
    qdiiApi.getQuota(),
    etfApi.getMomentum('conservative'),
    industryApi.getRanking(),
    backtestApi.getRuns(),
    fundApi.getEvaluated(),
  ])

  if (qdiiR.status === 'fulfilled') {
    const funds = qdiiR.value.data?.funds || []
    qdiiCount.value = funds.length
    const tightCount = funds.filter((f: any) => {
      const s = f.apply_status || f.quota_status || ''
      return s.includes('限') || s.includes('暂停') || (f.premium ?? 0) > 5
    }).length
    qdiiStatus.value = tightCount > 0 ? `${tightCount} 支告警` : '正常'
    stats.value.qdii = funds.length
  }

  if (etfR.status === 'fulfilled') {
    const data = etfR.value.data
    etfSignal.value = data?.signal || '观望'
    holdingCount.value = data?.holdings?.length || 0
    const top = data?.candidates?.[0]
    if (top) {
      etfTop.value = top.name || top.code
    }
    stats.value.etf = data?.candidates?.length || 0
  }

  if (indR.status === 'fulfilled') {
    const r0 = indR.value.data?.ranking?.[0]
    if (r0) {
      hotIndustry.value = r0.industry
      indChange.value = r0.change_pct ?? null
    }
  }

  if (btR.status === 'fulfilled') {
    stats.value.backtest = btR.value.data?.runs?.length || btR.value.data?.length || 0
  }

  if (favR.status === 'fulfilled') {
    stats.value.eval = (favR.value.data?.data || []).length
  }

  lastUpdateLabel.value = new Date().toLocaleString('zh-CN', { hour12: false })
  updateStatusLabel.value = '运行正常'

  await loadActivity()
})
</script>

<style scoped>
.home {
  max-width: 1400px;
  margin: 0 auto;
}

/* ============ Hero ============ */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 36px 40px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 16px;
  color: white;
  margin-bottom: 24px;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.25);
}

.hero-title {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 8px 0;
  letter-spacing: 1px;
}

.hero-subtitle {
  font-size: 14px;
  margin: 0;
  opacity: 0.85;
}

.hero-stats {
  display: flex;
  align-items: center;
  gap: 0;
  background: rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  padding: 16px 8px;
}

.hero-stat {
  padding: 0 24px;
  text-align: center;
  min-width: 86px;
}

.hero-stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.hero-stat-label {
  font-size: 12px;
  opacity: 0.85;
  margin-top: 6px;
}

.hero-stat-divider {
  width: 1px;
  height: 36px;
  background: rgba(255, 255, 255, 0.25);
}

/* ============ Stat Row (4 卡片) ============ */
.stat-row {
  margin-bottom: 24px;
}

.stat-card {
  position: relative;
  padding: 20px;
  border-radius: 12px;
  color: white;
  cursor: pointer;
  overflow: hidden;
  min-height: 132px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
}

.card-gradient-purple { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.card-gradient-pink   { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
.card-gradient-blue   { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
.card-gradient-green  { background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 13px;
  opacity: 0.85;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 6px;
}

.stat-desc {
  font-size: 12px;
  opacity: 0.85;
}

/* ============ 双栏 ============ */
.main-row {
  margin-bottom: 24px;
}

.dashboard-card {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  min-height: 380px;
}

.card-section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* ============ 快捷入口 ============ */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.quick-tile {
  padding: 18px;
  border-radius: 12px;
  color: white;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 96px;
}

.quick-tile:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

.quick-tile-label {
  font-size: 16px;
  font-weight: 600;
  margin-top: 4px;
}

.quick-tile-desc {
  font-size: 12px;
  opacity: 0.85;
}

/* ============ 最近操作 ============ */
.activity-list {
  display: flex;
  flex-direction: column;
  max-height: 520px;
  overflow-y: auto;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 8px;
  border-bottom: 1px solid #f5f7fa;
  cursor: pointer;
  transition: background 0.15s ease;
}

.activity-item:last-child {
  border-bottom: none;
}

.activity-item:hover {
  background: #f9fafc;
}

.activity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.kind-fund_eval .activity-dot { background: #f5576c; }
.kind-backtest_run .activity-dot { background: #667eea; }
.kind-etf_refresh .activity-dot { background: #4facfe; }
.kind-qdii_refresh .activity-dot { background: #43e97b; }
.kind-industry_refresh .activity-dot { background: #fa709a; }

.activity-main {
  flex: 1;
  min-width: 0;
}

.activity-title {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-summary {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.activity-time {
  font-size: 12px;
  color: #c0c4cc;
  white-space: nowrap;
  flex-shrink: 0;
}

/* ============ 通用 ============ */
.text-success { color: #67c23a; }
.text-warning { color: #e6a23c; }
.text-danger { color: #f56c6c; }
</style>

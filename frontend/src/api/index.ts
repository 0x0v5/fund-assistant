import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000  // 60秒超时
})

// QDII API
export const qdiiApi = {
  getQuota: () => api.get('/qdii/quota'),
  getQuotaDetail: (code: string) => api.get(`/qdii/quota/${code}`),
  refreshQuota: () => api.post('/qdii/quota/refresh')
}

// 基金评测 API
export const fundApi = {
  evaluate: (code: string) => api.get(`/fund/eval/${code}`),
  refreshEval: (code: string) => api.post(`/fund/eval/${code}/refresh`),
  batchRefreshEval: () => api.post('/fund/eval/batch-refresh', []),
  getHistory: (code: string, period: string = '1y') => api.get(`/fund/history/${code}`, { params: { period } }),
  getEvalHistory: (code: string, days: number = 30) => api.get('/fund/eval/history', { params: { code, days } }),
  search: (keyword: string) => api.get('/fund/search', { params: { keyword } }),
  getInfo: (code: string) => api.get(`/fund/info/${code}`),
  getFavorites: () => api.get('/fund/favorites'),
  getEvaluated: () => api.get('/fund/evaluated'),
  addFavorite: (code: string) => api.post(`/fund/favorites/${code}`),
  removeFavorite: (code: string) => api.delete(`/fund/favorites/${code}`),
}

// ETF 轮动 API
export const etfApi = {
  getMomentum: (strategy: string = 'aggressive') => api.get('/etf/momentum', { params: { strategy } }),
  getCandidates: () => api.get('/etf/candidates'),
  getHistory: () => api.get('/etf/history'),
  refreshMomentum: () => api.post('/etf/momentum/refresh'),
  compareSources: (strategy: string = 'aggressive') => api.get('/etf/compare-sources', { params: { strategy } }),
}

// 行业基金 API
export const industryApi = {
  getFunds: (industry?: string) => api.get('/industry/funds', { params: { industry } }),
  getRanking: () => api.get('/industry/ranking'),
  refreshRanking: () => api.post('/industry/ranking/refresh'),
}

// 回测 API
export const backtestApi = {
  getStrategies: () => api.get('/backtest/strategies'),
  runBacktest: (data: any) => api.post('/backtest/run', data),
  getRuns: (params?: any) => api.get('/backtest/runs', { params }),
  getRun: (runId: number) => api.get(`/backtest/runs/${runId}`),
  getEquity: (runId: number) => api.get(`/backtest/runs/${runId}/equity`),
  getTrades: (runId: number) => api.get(`/backtest/runs/${runId}/trades`),
  compareRuns: (runIds: number[]) => api.post('/backtest/compare', { run_ids: runIds }),
  deleteRun: (runId: number) => api.delete(`/backtest/runs/${runId}`),
}

// 最近活动 API
export const activityApi = {
  getRecent: (limit: number = 12) => api.get('/activity/recent', { params: { limit } })
}

export default api

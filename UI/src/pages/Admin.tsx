import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchRulesConfig,
  fetchRulesSchema,
  resetRulesConfig,
  saveRulesConfig,
} from '../api/client'
import type { RuleCondition, RuleStrategy, RulesConfig, RulesSchema } from '../types'

const STYLES = ['swing', 'intraday', 'positional'] as const
type Style = (typeof STYLES)[number]

function emptyCondition(): RuleCondition {
  return {
    id: `cond_${Date.now()}`,
    label: 'New condition',
    field: 'close',
    operator: 'gt',
    value: null,
    ref_field: null,
    weight: 1,
    reason_template: '',
  }
}

function emptyStrategy(style: Style): RuleStrategy {
  const id = `strategy_${Date.now()}`
  return {
    id,
    name: 'New Strategy',
    style,
    description: '',
    min_confidence: 0.55,
    enabled: true,
    conditions: [emptyCondition()],
  }
}

function usesRefField(operator: string, schema: RulesSchema | null) {
  return schema?.ref_operators.includes(operator) ?? false
}

function usesValue(operator: string, schema: RulesSchema | null) {
  return schema?.value_operators.includes(operator) ?? false
}

function formatBetween(value: RuleCondition['value']) {
  if (Array.isArray(value)) return `${value[0]}, ${value[1]}`
  return '50, 70'
}

function parseBetween(raw: string): [number, number] {
  const parts = raw.split(',').map((s) => Number(s.trim()))
  return [parts[0] || 0, parts[1] || 0]
}

export default function Admin() {
  const [schema, setSchema] = useState<RulesSchema | null>(null)
  const [config, setConfig] = useState<RulesConfig | null>(null)
  const [activeStyle, setActiveStyle] = useState<Style>('swing')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setMessage(null)
    try {
      const [schemaData, configData] = await Promise.all([
        fetchRulesSchema(),
        fetchRulesConfig(),
      ])
      setSchema(schemaData)
      setConfig(configData)
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message ?? 'Failed to load rules' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const strategies = useMemo(() => {
    if (!config) return []
    return config.strategies.filter((s) => s.style === activeStyle)
  }, [config, activeStyle])

  const updateStrategy = (id: string, patch: Partial<RuleStrategy>) => {
    if (!config) return
    setConfig({
      ...config,
      strategies: config.strategies.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    })
  }

  const updateCondition = (strategyId: string, condId: string, patch: Partial<RuleCondition>) => {
    if (!config) return
    setConfig({
      ...config,
      strategies: config.strategies.map((s) => {
        if (s.id !== strategyId) return s
        return {
          ...s,
          conditions: s.conditions.map((c) => (c.id === condId ? { ...c, ...patch } : c)),
        }
      }),
    })
  }

  const addStrategy = () => {
    if (!config) return
    const strategy = emptyStrategy(activeStyle)
    setConfig({ ...config, strategies: [...config.strategies, strategy] })
    setExpandedId(strategy.id)
  }

  const removeStrategy = (id: string) => {
    if (!config) return
    setConfig({ ...config, strategies: config.strategies.filter((s) => s.id !== id) })
    if (expandedId === id) setExpandedId(null)
  }

  const addCondition = (strategyId: string) => {
    if (!config) return
    setConfig({
      ...config,
      strategies: config.strategies.map((s) =>
        s.id === strategyId
          ? { ...s, conditions: [...s.conditions, emptyCondition()] }
          : s,
      ),
    })
  }

  const removeCondition = (strategyId: string, condId: string) => {
    if (!config) return
    setConfig({
      ...config,
      strategies: config.strategies.map((s) => {
        if (s.id !== strategyId) return s
        const conditions = s.conditions.filter((c) => c.id !== condId)
        return { ...s, conditions: conditions.length ? conditions : [emptyCondition()] }
      }),
    })
  }

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    setMessage(null)
    try {
      const saved = await saveRulesConfig(config)
      setConfig(saved)
      setMessage({ type: 'ok', text: `Saved ${saved.strategies.length} strategies to JSON` })
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setMessage({
        type: 'err',
        text: err.response?.data?.detail ?? err.message ?? 'Save failed',
      })
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!window.confirm('Reset all rules to built-in defaults? This overwrites the JSON file.')) return
    setSaving(true)
    setMessage(null)
    try {
      const saved = await resetRulesConfig()
      setConfig(saved)
      setMessage({ type: 'ok', text: 'Reset to built-in defaults' })
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message ?? 'Reset failed' })
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="page-state">Loading rule configuration…</div>

  return (
    <div className="admin-page">
      <header className="page-header">
        <div>
          <h1>Admin — Scanner Rules</h1>
          <p>Configure swing, intraday, and positional strategies. Saved to JSON on the server.</p>
          {config?.file_path && (
            <p className="admin-path">
              <code>{config.file_path}</code>
              {config.updated_at && <span> · updated {new Date(config.updated_at).toLocaleString()}</span>}
            </p>
          )}
        </div>
        <div className="admin-actions">
          <button type="button" className="btn secondary" onClick={handleReset} disabled={saving}>
            Reset defaults
          </button>
          <button type="button" className="btn primary" onClick={handleSave} disabled={saving || !config}>
            {saving ? 'Saving…' : 'Save to JSON'}
          </button>
        </div>
      </header>

      {message && (
        <div className={`admin-banner ${message.type}`}>{message.text}</div>
      )}

      <div className="admin-style-tabs">
        {STYLES.map((style) => (
          <button
            key={style}
            type="button"
            className={`style-tab ${style}${activeStyle === style ? ' active' : ''}`}
            onClick={() => setActiveStyle(style)}
          >
            {style.charAt(0).toUpperCase() + style.slice(1)}
            <span className="count">
              {config?.strategies.filter((s) => s.style === style).length ?? 0}
            </span>
          </button>
        ))}
        <button type="button" className="btn ghost" onClick={addStrategy}>
          + Add strategy
        </button>
      </div>

      <div className="admin-strategies">
        {strategies.length === 0 && (
          <p className="empty">No strategies for {activeStyle}. Click “Add strategy” to create one.</p>
        )}
        {strategies.map((strategy) => {
          const open = expandedId === strategy.id
          return (
            <article key={strategy.id} className={`admin-strategy${strategy.enabled ? '' : ' disabled'}`}>
              <div className="admin-strategy-head" onClick={() => setExpandedId(open ? null : strategy.id)}>
                <div>
                  <h2>{strategy.name}</h2>
                  <p>{strategy.description || 'No description'}</p>
                  <span className="meta">
                    {strategy.id} · {strategy.conditions.length} conditions · min conf{' '}
                    {Math.round(strategy.min_confidence * 100)}%
                  </span>
                </div>
                <div className="admin-strategy-badges">
                  <label className="toggle" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={strategy.enabled}
                      onChange={(e) => updateStrategy(strategy.id, { enabled: e.target.checked })}
                    />
                    Enabled
                  </label>
                  <span className="chevron">{open ? '▾' : '▸'}</span>
                </div>
              </div>

              {open && (
                <div className="admin-strategy-body">
                  <div className="admin-form-grid">
                    <label>
                      ID
                      <input
                        value={strategy.id}
                        onChange={(e) => updateStrategy(strategy.id, { id: e.target.value })}
                      />
                    </label>
                    <label>
                      Name
                      <input
                        value={strategy.name}
                        onChange={(e) => updateStrategy(strategy.id, { name: e.target.value })}
                      />
                    </label>
                    <label>
                      Style
                      <select
                        value={strategy.style}
                        onChange={(e) =>
                          updateStrategy(strategy.id, { style: e.target.value as Style })
                        }
                      >
                        {STYLES.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Min confidence (0–1)
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={strategy.min_confidence}
                        onChange={(e) =>
                          updateStrategy(strategy.id, { min_confidence: Number(e.target.value) })
                        }
                      />
                    </label>
                    <label className="full">
                      Description
                      <input
                        value={strategy.description}
                        onChange={(e) => updateStrategy(strategy.id, { description: e.target.value })}
                      />
                    </label>
                  </div>

                  <div className="admin-conditions">
                    <div className="admin-conditions-head">
                      <h3>Conditions</h3>
                      <button type="button" className="btn ghost small" onClick={() => addCondition(strategy.id)}>
                        + Add condition
                      </button>
                    </div>

                    {strategy.conditions.map((cond) => (
                      <div key={cond.id} className="admin-condition">
                        <div className="admin-form-grid">
                          <label>
                            Condition ID
                            <input
                              value={cond.id}
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { id: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            Label
                            <input
                              value={cond.label}
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { label: e.target.value })
                              }
                            />
                          </label>
                          <label>
                            Field
                            <select
                              value={cond.field}
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { field: e.target.value })
                              }
                            >
                              {(schema?.fields ?? [cond.field]).map((f) => (
                                <option key={f} value={f}>{f}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Operator
                            <select
                              value={cond.operator}
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { operator: e.target.value })
                              }
                            >
                              {(schema?.operators ?? []).map((op) => (
                                <option key={op.value} value={op.value}>{op.label}</option>
                              ))}
                            </select>
                          </label>
                          {usesRefField(cond.operator, schema) && (
                            <label>
                              Reference field
                              <select
                                value={cond.ref_field ?? ''}
                                onChange={(e) =>
                                  updateCondition(strategy.id, cond.id, {
                                    ref_field: e.target.value || null,
                                  })
                                }
                              >
                                <option value="">—</option>
                                {(schema?.fields ?? []).map((f) => (
                                  <option key={f} value={f}>{f}</option>
                                ))}
                              </select>
                            </label>
                          )}
                          {usesValue(cond.operator, schema) && cond.operator !== 'between' && (
                            <label>
                              Value
                              <input
                                type={cond.operator === 'eq' && typeof cond.value === 'boolean' ? 'text' : 'number'}
                                value={String(cond.value ?? '')}
                                onChange={(e) => {
                                  const raw = e.target.value
                                  let value: RuleCondition['value'] = raw === '' ? null : Number(raw)
                                  if (raw === 'true') value = true
                                  if (raw === 'false') value = false
                                  updateCondition(strategy.id, cond.id, { value })
                                }}
                              />
                            </label>
                          )}
                          {cond.operator === 'between' && (
                            <label>
                              Range (min, max)
                              <input
                                value={formatBetween(cond.value)}
                                onChange={(e) =>
                                  updateCondition(strategy.id, cond.id, {
                                    value: parseBetween(e.target.value),
                                  })
                                }
                              />
                            </label>
                          )}
                          <label>
                            Weight
                            <input
                              type="number"
                              min={0.1}
                              step={0.1}
                              value={cond.weight}
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { weight: Number(e.target.value) })
                              }
                            />
                          </label>
                          <label className="full">
                            Reason template
                            <input
                              value={cond.reason_template}
                              placeholder="e.g. RSI {value:.0f}"
                              onChange={(e) =>
                                updateCondition(strategy.id, cond.id, { reason_template: e.target.value })
                              }
                            />
                          </label>
                        </div>
                        <button
                          type="button"
                          className="btn danger small"
                          onClick={() => removeCondition(strategy.id, cond.id)}
                        >
                          Remove condition
                        </button>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    className="btn danger"
                    onClick={() => removeStrategy(strategy.id)}
                  >
                    Delete strategy
                  </button>
                </div>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}

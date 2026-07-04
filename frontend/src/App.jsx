import { useState, useEffect, useRef, useCallback } from 'react'
import TextareaAutosize from 'react-textarea-autosize';
import './App.css'
// In development, use localhost:8000. In production, use empty string to use relative path (proxied by Nginx).
const API = import.meta.env.DEV ? 'http://localhost:8000' : '';
const DRAFT_KEY = 'audit-generator-draft';

const IMAGE_STYLES = [
  { value: '3d_icon', label: '3D-иконка' },
  { value: 'flat_vector', label: 'Плоский вектор' },
  { value: 'isometric', label: 'Изометрия' },
];

function loadDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function App() {
  const draft = useRef(loadDraft()).current;

  const [step, setStep] = useState(draft?.step || 1);
  const [loading, setLoading] = useState(false);
  const [auditType, setAuditType] = useState(draft?.auditType || 'express');
  const [formData, setFormData] = useState(draft?.formData || {
    general_data: '',
    vulnerabilities: '',
    conclusions: ''
  });
  const [auditData, setAuditData] = useState(draft?.auditData || null);
  const [revisionText, setRevisionText] = useState("");
  const [revising, setRevising] = useState(false);
  const [hints, setHints] = useState([]);
  const [imageStyle, setImageStyle] = useState(draft?.imageStyle || '3d_icon');
  const [batchProgress, setBatchProgress] = useState(null); // {done, total}
  const [toasts, setToasts] = useState([]);
  const [reviseCaseOpen, setReviseCaseOpen] = useState({}); // {idx: comment}
  const [saveToMemory, setSaveToMemory] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem('audit-theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('audit-theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const addToast = useCallback((message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4500);
  }, []);

  useEffect(() => {
    fetch(`${API}/api/hints`)
      .then(res => res.json())
      .then(data => setHints(data.hints || []))
      .catch(err => console.error("Failed to load hints:", err));
  }, []);

  // Автосохранение черновика (debounce 500мс)
  useEffect(() => {
    const t = setTimeout(() => {
      const cleanAudit = auditData ? {
        ...auditData,
        cases: auditData.cases.map(({ imageGenerating, textRevising, ...c }) => c)
      } : null;
      const payload = { step, auditType, formData, auditData: cleanAudit, imageStyle };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
      } catch {
        // Квота localStorage — сохраняем без картинок
        try {
          const light = cleanAudit ? {
            ...cleanAudit,
            cases: cleanAudit.cases.map(({ image_b64, ...c }) => c)
          } : null;
          localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...payload, auditData: light }));
        } catch { /* совсем не влезло — пропускаем */ }
      }
    }, 500);
    return () => clearTimeout(t);
  }, [step, auditType, formData, auditData, imageStyle]);

  const resetAll = () => {
    if (!confirm("Начать заново? Текущий черновик будет удален.")) return;
    localStorage.removeItem(DRAFT_KEY);
    setStep(1);
    setFormData({ general_data: '', vulnerabilities: '', conclusions: '' });
    setAuditData(null);
    setRevisionText("");
    setBatchProgress(null);
    setReviseCaseOpen({});
  };

  const updateCase = (index, patch) => {
    setAuditData(prev => {
      if (!prev) return prev;
      const cases = prev.cases.map((c, i) => i === index ? { ...c, ...patch } : c);
      return { ...prev, cases };
    });
  };

  const handleParse = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/parse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...formData, audit_type: auditType })
      });
      if (!res.ok) {
        addToast("Ошибка от сервера: " + (await res.text()).slice(0, 200), 'error');
        setLoading(false);
        return;
      }
      const data = await res.json();
      setAuditData(data);
      setStep(2);
      addToast("Структура аудита готова", 'success');
    } catch (err) {
      addToast("Ошибка при парсинге: " + err, 'error');
    }
    setLoading(false);
  };

  const handleCaseChange = (index, field, value) => {
    updateCase(index, { [field]: value });
  };

  const generateImageFor = async (index, prompt) => {
    updateCase(index, { imageGenerating: true });
    try {
      const res = await fetch(`${API}/api/generate_image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, style: imageStyle })
      });
      if (res.ok) {
        const data = await res.json();
        updateCase(index, { image_b64: data.image_b64, imageGenerating: false });
        return true;
      }
      updateCase(index, { imageGenerating: false });
      addToast(`Кейс ${index + 1}: не удалось сгенерировать картинку`, 'error');
      return false;
    } catch (e) {
      console.error(e);
      updateCase(index, { imageGenerating: false });
      addToast(`Кейс ${index + 1}: ошибка сети при генерации`, 'error');
      return false;
    }
  };

  const handleRegenerateImage = (index) => {
    const prompt = auditData.cases[index].image_prompt;
    return generateImageFor(index, prompt);
  };

  const handleGenerateAllImages = async () => {
    const targets = auditData.cases
      .map((c, i) => ({ c, i }))
      .filter(({ c }) => !c.image_b64);
    if (!targets.length) {
      addToast("Все картинки уже сгенерированы");
      return;
    }
    setBatchProgress({ done: 0, total: targets.length });
    let done = 0;
    await Promise.all(targets.map(({ c, i }) =>
      generateImageFor(i, c.image_prompt).then(() => {
        done += 1;
        setBatchProgress({ done, total: targets.length });
      })
    ));
    setBatchProgress(null);
    addToast(`Готово: ${targets.length} картинок`, 'success');
  };

  const handleReviseCase = async (index) => {
    const comment = reviseCaseOpen[index] || "";
    updateCase(index, { textRevising: true });
    try {
      const res = await fetch(`${API}/api/revise_case`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case: auditData.cases[index],
          comment,
          audit_type: auditType,
          general_data: formData.general_data
        })
      });
      if (!res.ok) {
        addToast("Ошибка от сервера: " + (await res.text()).slice(0, 200), 'error');
        updateCase(index, { textRevising: false });
        return;
      }
      const newCase = await res.json();
      setAuditData(prev => {
        const cases = prev.cases.map((c, i) => i === index ? { ...newCase, imageGenerating: c.imageGenerating } : c);
        return { ...prev, cases };
      });
      setReviseCaseOpen(prev => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
      addToast(`Кейс ${index + 1} переписан`, 'success');
    } catch (err) {
      addToast("Ошибка: " + err, 'error');
      updateCase(index, { textRevising: false });
    }
  };

  const handleRevise = async () => {
    if (!revisionText.trim()) return;
    setRevising(true);
    try {
      const res = await fetch(`${API}/api/revise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_data: auditData,
          revision_prompt: revisionText,
          audit_type: auditType
        })
      });
      if (!res.ok) {
        addToast("Ошибка от сервера: " + (await res.text()).slice(0, 200), 'error');
        setRevising(false);
        return;
      }
      const data = await res.json();
      setAuditData(data);
      setRevisionText("");
      addToast("Правки применены", 'success');
    } catch (err) {
      addToast("Ошибка при применении правок: " + err, 'error');
    }
    setRevising(false);
  };

  const handleGeneratePptx = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/generate_pptx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: auditData, audit_type: auditType, save_to_memory: saveToMemory })
      });

      if (!res.ok) {
        addToast("Ошибка при генерации PPTX: " + (await res.text()).slice(0, 200), 'error');
        setLoading(false);
        return;
      }

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Отчет_${auditData.client_name.replace(/ /g, '_')}.pptx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      addToast(saveToMemory ? "Отчет скачан и сохранен в базу знаний ИИ" : "Отчет скачан", 'success');
    } catch (err) {
      addToast("Ошибка сети при скачивании: " + err, 'error');
    }
    setLoading(false);
  };

  return (
    <div className="container">
      <div className="flex-between" style={{marginBottom: '2rem', alignItems: 'center'}}>
        <h1 className="title" style={{margin: 0}}>Audit Generator AI</h1>
        <button className="btn" onClick={toggleTheme} style={{padding: '0.5rem 1rem', fontSize: '1.2rem', borderRadius: '50px'}}>
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </div>

      {step === 1 && (
        <div className="glass-panel">
          <div className="flex-between" style={{marginBottom: '2rem'}}>
            <h2>Ввод данных аудита</h2>
            <div className="switch-wrap">
              <label>Тип аудита:</label>
              <select value={auditType} onChange={e => setAuditType(e.target.value)} style={{width: 'auto'}}>
                <option value="express">Экспресс-аудит</option>
                <option value="full">Полный аудит (с рекомендациями)</option>
              </select>
            </div>
          </div>

          <div className="input-group">
            <label>Общие данные о клиенте (Название, адрес, сфера, размер штата)</label>
            <TextareaAutosize
              value={formData.general_data}
              onChange={e => setFormData({...formData, general_data: e.target.value})}
              placeholder="Например: ТОО Ромашка, 100 сотрудников..."
            />
          </div>

          <div className="input-group">
            <label>Выявленные уязвимости и проблемы</label>
            <TextareaAutosize
              value={formData.vulnerabilities}
              onChange={e => setFormData({...formData, vulnerabilities: e.target.value})}
              placeholder="Что нашли на объекте? (например: открыт RDP, пиратская винда, бэкапов нет)"
            />
            <div style={{marginTop: '0.5rem'}}>
              <select
                className="input-field"
                style={{padding: '0.5rem'}}
                onChange={(e) => {
                  if (e.target.value) {
                    setFormData({
                      ...formData,
                      vulnerabilities: formData.vulnerabilities + (formData.vulnerabilities ? ', ' : '') + e.target.value
                    });
                    e.target.value = "";
                  }
                }}
              >
                <option value="">-- Выбрать из частых уязвимостей --</option>
                {Object.entries(
                  hints.reduce((acc, h) => {
                    const hint = typeof h === 'string' ? { text: h, category: 'Прочее' } : h;
                    (acc[hint.category] = acc[hint.category] || []).push(hint.text);
                    return acc;
                  }, {})
                ).map(([category, items]) => (
                  <optgroup key={category} label={category}>
                    {items.map((text, i) => <option key={i} value={text}>{text}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
          </div>

          <div className="input-group">
            <label>Заключение / Выводы</label>
            <TextareaAutosize
              value={formData.conclusions}
              onChange={e => setFormData({...formData, conclusions: e.target.value})}
              placeholder="Итоговые предложения..."
            />
          </div>

          <div className="flex-between">
            <button className="btn" onClick={handleParse} disabled={loading}>
              {loading ? <div className="loader"></div> : "Сгенерировать структуру"}
            </button>
            {(auditData || formData.general_data || formData.vulnerabilities) && (
              <button className="btn-small" onClick={resetAll}>Очистить черновик</button>
            )}
          </div>
          {auditData && (
            <p style={{marginTop: '1rem', color: 'var(--text-muted)', fontSize: '0.9rem'}}>
              Есть сохраненный черновик структуры — <a href="#" style={{color: 'var(--primary)'}} onClick={e => { e.preventDefault(); setStep(2); }}>вернуться к нему</a>.
            </p>
          )}
        </div>
      )}

      {step === 2 && auditData && (
        <div className="result-container" style={{animation: 'fadeIn 0.5s'}}>
          <datalist id="category-options">
            <option value="I. Серверная инфраструктура" />
            <option value="II. Сеть и ИТ-поддержка" />
            <option value="III. Безопасность" />
            <option value="IV. 1C" />
            <option value="V. Видеонаблюдение и СКУД" />
          </datalist>

          <div className="flex-between" style={{marginBottom: '2rem'}}>
            <h2>Предпросмотр: {auditData.client_name}</h2>
            <div style={{display: 'flex', gap: '0.5rem'}}>
              <button className="btn" onClick={() => setStep(1)} style={{background: 'transparent', border: '1px solid var(--border-glass)'}}>Назад</button>
              <button className="btn-small" onClick={resetAll}>Начать заново</button>
            </div>
          </div>

          <div className="input-group">
            <label>Текст обзора (слайд 2)</label>
            <TextareaAutosize
              value={auditData.review}
              onChange={e => setAuditData({...auditData, review: e.target.value})}
              minRows={4}
            />
          </div>

          <h3>Кейсы ({auditData.cases.length})</h3>
          <div className="cases-grid">
            {auditData.cases.map((c, i) => (
              <div key={i} className="glass-panel case-card" style={{padding: '1.5rem'}}>
                <div className="flex-between">
                  <h4>Кейс {i+1}</h4>
                  <span className={`badge ${c.priority === 'ПЕРВЫЙ ПРИОРИТЕТ' ? 'red' : c.priority === 'ВТОРОЙ ПРИОРИТЕТ' ? 'orange' : 'yellow'}`}>
                    {c.priority}
                  </span>
                </div>

                <TextareaAutosize value={c.title} onChange={e => handleCaseChange(i, 'title', e.target.value)} minRows={2} />
                <input
                  list="category-options"
                  value={c.category}
                  onChange={e => handleCaseChange(i, 'category', e.target.value)}
                  placeholder="Введите или выберите раздел..."
                  style={{width: '100%', marginBottom: '1rem'}}
                />

                <div>
                  <label style={{fontSize: '0.85rem'}}>Уязвимость:</label>
                  <TextareaAutosize value={c.vulnerability} onChange={e => handleCaseChange(i, 'vulnerability', e.target.value)} minRows={3}/>
                </div>

                <div>
                  <label style={{fontSize: '0.85rem'}}>Риски:</label>
                  <TextareaAutosize value={c.risk} onChange={e => handleCaseChange(i, 'risk', e.target.value)} minRows={3}/>
                </div>

                {auditType === 'full' && (
                  <div>
                    <label style={{fontSize: '0.85rem'}}>Рекомендации:</label>
                    <TextareaAutosize value={c.recommendation || ''} onChange={e => handleCaseChange(i, 'recommendation', e.target.value)} minRows={3}/>
                  </div>
                )}

                <div className="case-tools">
                  {c.textRevising ? (
                    <div className="loader" style={{width: 18, height: 18}}></div>
                  ) : reviseCaseOpen[i] !== undefined ? null : (
                    <button className="btn-small" onClick={() => setReviseCaseOpen(prev => ({...prev, [i]: ""}))}>
                      🪄 Улучшить текст ИИ
                    </button>
                  )}
                </div>

                {reviseCaseOpen[i] !== undefined && !c.textRevising && (
                  <div className="revise-case-box">
                    <TextareaAutosize
                      value={reviseCaseOpen[i]}
                      onChange={e => setReviseCaseOpen(prev => ({...prev, [i]: e.target.value}))}
                      placeholder="Что улучшить? (пусто = просто переписать качественнее)"
                      minRows={2}
                      style={{flex: 1}}
                    />
                    <button className="btn-small" onClick={() => handleReviseCase(i)}>➤</button>
                    <button className="btn-small" onClick={() => setReviseCaseOpen(prev => {
                      const next = {...prev}; delete next[i]; return next;
                    })}>✕</button>
                  </div>
                )}

                <div>
                  <label style={{fontSize: '0.85rem'}}>Промпт картинки (англ.):</label>
                  <TextareaAutosize
                    className="image-prompt-input"
                    value={c.image_prompt}
                    onChange={e => handleCaseChange(i, 'image_prompt', e.target.value)}
                    minRows={1}
                  />
                </div>

                <div className="case-image-wrap">
                  {c.imageGenerating ? (
                    <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center'}}>
                      <div className="loader"></div>
                    </div>
                  ) : c.image_b64 ? (
                    <img src={c.image_b64} alt="Case visual" />
                  ) : (
                    <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',justifyContent:'center', color: 'var(--text-muted)', textAlign: 'center', padding: '1rem'}}>
                      Нет картинки
                    </div>
                  )}

                  {!c.imageGenerating && (
                    <div className="case-image-overlay">
                      <button className="btn" style={{padding: '0.5rem 1rem', fontSize: '0.9rem'}} onClick={() => handleRegenerateImage(i)}>
                        {c.image_b64 ? "Перегенерировать" : "Сгенерировать"}
                      </button>
                    </div>
                  )}
                </div>

              </div>
            ))}
          </div>

          <h3 style={{marginTop: '2rem'}}>Выводы (последний слайд)</h3>
          {auditData.conclusions.map((conc, i) => (
            <input key={i} value={conc} style={{marginBottom: '0.5rem'}} onChange={e => {
              const newData = {...auditData};
              newData.conclusions[i] = e.target.value;
              setAuditData(newData);
            }}/>
          ))}

          <div className="glass-panel" style={{marginTop: '2rem', background: 'rgba(0,0,0,0.2)', border: '1px dashed var(--primary)'}}>
            <h3>Умные правки ИИ</h3>
            <p style={{fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '1rem'}}>
              Напишите, что нужно изменить в макете (например: "Удали кейс про антивирусы и добавь кейс про плохой интернет", "Сделай описания рисков более строгими").
            </p>
            <div className="input-group">
              <TextareaAutosize
                value={revisionText}
                onChange={e => setRevisionText(e.target.value)}
                placeholder="Ваши комментарии и пожелания для ИИ..."
                minRows={5}
              />
            </div>
            <button className="btn" onClick={handleRevise} disabled={revising} style={{fontSize: '1rem'}}>
              {revising ? <div className="loader"></div> : "Применить правки"}
            </button>
          </div>

          <div style={{marginTop: '3rem', textAlign: 'center'}}>
            <div style={{marginBottom: '1rem'}}>
              <span className="style-select-wrap">
                <label style={{fontSize: '0.9rem'}}>Стиль картинок:</label>
                <select value={imageStyle} onChange={e => setImageStyle(e.target.value)}>
                  {IMAGE_STYLES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </span>
              <button className="btn" onClick={handleGenerateAllImages} disabled={loading || revising || !!batchProgress} style={{fontSize: '1rem', padding: '1rem 2rem'}}>
                {batchProgress ? `Генерация ${batchProgress.done}/${batchProgress.total}...` : "Сгенерировать все картинки"}
              </button>
            </div>
            {batchProgress && (
              <div className="progress-wrap">
                <div className="progress-bar">
                  <div className="progress-bar-fill" style={{width: `${(batchProgress.done / batchProgress.total) * 100}%`}}></div>
                </div>
                <span style={{fontSize: '0.9rem', color: 'var(--text-muted)'}}>{batchProgress.done}/{batchProgress.total}</span>
              </div>
            )}
            <div style={{marginTop: '1rem'}}>
              <button className="btn" onClick={handleGeneratePptx} disabled={loading || revising} style={{fontSize: '1.25rem', padding: '1rem 3rem'}}>
                {loading ? <div className="loader"></div> : "💾 Скачать PPTX Отчет"}
              </button>
              <label className="memory-checkbox">
                <input
                  type="checkbox"
                  checked={saveToMemory}
                  onChange={e => setSaveToMemory(e.target.checked)}
                />
                <span>
                  Сохранить этот аудит в базу знаний ИИ — он будет использоваться как образец,
                  чтобы будущие отчеты получались точнее и качественнее
                </span>
              </label>
            </div>
          </div>
        </div>
      )}

      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>{t.message}</div>
        ))}
      </div>
    </div>
  )
}

export default App

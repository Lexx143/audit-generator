import { useState, useEffect, useRef, useCallback } from 'react'
import TextareaAutosize from 'react-textarea-autosize';
import './App.css'
// In development, use the current host so the app also works when opened
// from a phone on the same network. In production, use empty string to use
// relative path (proxied by Nginx).
const API = import.meta.env.DEV ? `http://${window.location.hostname}:8000` : '';
const DRAFT_KEY = 'audit-generator-draft';

const IMAGE_STYLES = [
  { value: '3d_icon', label: '3D-иконка' },
  { value: 'flat_vector', label: 'Плоский вектор' },
  { value: 'isometric', label: 'Изометрия' },
];

// Номера разделов (I, II, ...) в макете не показываем — они проставляются
// автоматически при выгрузке отчета по порядку появления категорий
const stripCategoryNumber = (cat) => (cat || '').replace(/^\s*[IVXivx]+\.\s*/, '').trim();

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
  const [auditors, setAuditors] = useState([]);
  const [categories, setCategories] = useState([]);
  const [auditorId, setAuditorId] = useState(draft?.auditorId || '');
  const [newAuditor, setNewAuditor] = useState(null); // {name, photo_b64} | null
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
    fetch(`${API}/api/auditors`)
      .then(res => res.json())
      .then(data => setAuditors(data.auditors || []))
      .catch(err => console.error("Failed to load auditors:", err));
    fetch(`${API}/api/categories`)
      .then(res => res.json())
      .then(data => setCategories(data.categories || []))
      .catch(err => console.error("Failed to load categories:", err));
  }, []);

  const handleSaveCategory = async (index) => {
    const name = stripCategoryNumber(auditData.cases[index].category);
    if (!name) {
      addToast("Название категории пустое", 'error');
      return;
    }
    try {
      const res = await fetch(`${API}/api/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      if (!res.ok) {
        addToast("Не удалось сохранить категорию", 'error');
        return;
      }
      const data = await res.json();
      setCategories(data.categories || []);
      updateCase(index, { category: name, categoryCustom: false });
      addToast(`Категория «${name}» сохранена — доступна во всех кейсах`, 'success');
    } catch (e) {
      addToast("Ошибка сети: " + e, 'error');
    }
  };

  // Файл -> сжатый dataURL (максимум 1024px по большей стороне)
  const fileToDataUrl = (file, maxSide = 1024) => new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = reject;
    img.src = url;
  });

  // --- Кадрирование фото аудитора ---
  const CROP_VIEW = 260;
  const [photoCrop, setPhotoCrop] = useState(null); // {src, nw, nh, scale, minScale, x, y}
  const cropDragRef = useRef(null);

  const openPhotoCrop = async (file) => {
    try {
      const src = await fileToDataUrl(file, 1600);
      const img = new Image();
      img.onload = () => {
        const minScale = CROP_VIEW / Math.min(img.width, img.height);
        setPhotoCrop({
          src, nw: img.width, nh: img.height, scale: minScale, minScale,
          x: (CROP_VIEW - img.width * minScale) / 2,
          y: (CROP_VIEW - img.height * minScale) / 2,
        });
      };
      img.src = src;
    } catch {
      addToast("Не удалось прочитать фото", 'error');
    }
  };

  const clampCrop = (c) => {
    const w = c.nw * c.scale, h = c.nh * c.scale;
    return { ...c, x: Math.min(0, Math.max(CROP_VIEW - w, c.x)), y: Math.min(0, Math.max(CROP_VIEW - h, c.y)) };
  };

  const cropZoom = (newScale) => {
    setPhotoCrop(c => {
      const cx = (CROP_VIEW / 2 - c.x) / c.scale;
      const cy = (CROP_VIEW / 2 - c.y) / c.scale;
      return clampCrop({ ...c, scale: newScale, x: CROP_VIEW / 2 - cx * newScale, y: CROP_VIEW / 2 - cy * newScale });
    });
  };

  const applyCrop = () => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 512;
      const s = photoCrop.scale;
      canvas.getContext('2d').drawImage(img, -photoCrop.x / s, -photoCrop.y / s, CROP_VIEW / s, CROP_VIEW / s, 0, 0, 512, 512);
      setNewAuditor(prev => ({ ...prev, photo_b64: canvas.toDataURL('image/jpeg', 0.9) }));
      setPhotoCrop(null);
    };
    img.src = photoCrop.src;
  };

  const handleSaveAuditor = async () => {
    if (!newAuditor?.name?.trim()) {
      addToast("Укажите имя аудитора", 'error');
      return null;
    }
    try {
      const res = await fetch(`${API}/api/auditors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newAuditor.name, photo_b64: newAuditor.photo_b64 || null })
      });
      if (!res.ok) {
        addToast("Не удалось сохранить аудитора: " + (await res.text()).slice(0, 150), 'error');
        return null;
      }
      const saved = await res.json();
      setAuditors(prev => [...prev.filter(a => a.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      setAuditorId(saved.id);
      setNewAuditor(null);
      addToast(`Аудитор «${saved.name}» сохранен`, 'success');
      return saved;
    } catch (e) {
      addToast("Ошибка сети: " + e, 'error');
      return null;
    }
  };

  // Подбор картинок из библиотеки для похожего кейса
  const loadSuggestionsFor = async (caseObj, index, applyFirst) => {
    try {
      const res = await fetch(`${API}/api/image_suggestions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: caseObj.title, vulnerability: caseObj.vulnerability, n: 6 })
      });
      if (!res.ok) return;
      const data = await res.json();
      const imgs = (data.images || []).map(x => x.b64);
      if (!imgs.length) return;
      setAuditData(prev => {
        if (!prev || !prev.cases[index]) return prev;
        const cases = prev.cases.map((c, i) => {
          if (i !== index) return c;
          const patch = { ...c, suggestions: imgs, suggIdx: 0 };
          if (applyFirst && !c.image_b64) {
            patch.image_b64 = imgs[0];
            patch.image_reusable = true;
            patch.image_source = 'library';
          }
          return patch;
        });
        return { ...prev, cases };
      });
    } catch (e) {
      console.error("suggestions failed:", e);
    }
  };

  const cycleSuggestion = (index, dir) => {
    setAuditData(prev => {
      const cases = prev.cases.map((c, i) => {
        if (i !== index || !c.suggestions?.length) return c;
        const idx = ((c.suggIdx ?? 0) + dir + c.suggestions.length) % c.suggestions.length;
        return { ...c, suggIdx: idx, image_b64: c.suggestions[idx], image_reusable: true, image_source: 'library' };
      });
      return { ...prev, cases };
    });
  };

  const handleUploadImage = async (index, file) => {
    if (!file) return;
    try {
      const dataUrl = await fileToDataUrl(file);
      updateCase(index, { image_b64: dataUrl, image_source: 'uploaded', image_reusable: false });
      addToast(`Кейс ${index + 1}: картинка загружена`, 'success');
    } catch (e) {
      addToast("Не удалось прочитать файл: " + e, 'error');
    }
  };

  // Автосохранение черновика (debounce 500мс)
  useEffect(() => {
    const t = setTimeout(() => {
      const cleanAudit = auditData ? {
        ...auditData,
        cases: auditData.cases.map(({ imageGenerating, textRevising, suggestions, suggIdx, ...c }) => c)
      } : null;
      const payload = { step, auditType, formData, auditData: cleanAudit, imageStyle, auditorId };
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
  }, [step, auditType, formData, auditData, imageStyle, auditorId]);

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
      data.cases = data.cases.map(c => ({ ...c, category: stripCategoryNumber(c.category) }));
      setAuditData(data);
      setStep(2);
      addToast("Структура аудита готова", 'success');
      // Подтягиваем похожие картинки из библиотеки для каждого кейса
      data.cases.forEach((c, i) => loadSuggestionsFor(c, i, true));
    } catch (err) {
      addToast("Ошибка при парсинге: " + err, 'error');
    }
    setLoading(false);
  };

  const handleCaseChange = (index, field, value) => {
    updateCase(index, { [field]: value });
  };

  const handleDeleteCase = (index) => {
    if (auditData.cases.length <= 1) {
      addToast("Нельзя удалить последний кейс", 'error');
      return;
    }
    if (!confirm(`Удалить кейс ${index + 1} «${auditData.cases[index].title}»?`)) return;
    setAuditData(prev => ({ ...prev, cases: prev.cases.filter((_, i) => i !== index) }));
  };

  const handleAddCase = () => {
    if (auditData.cases.length >= 5) {
      addToast("Максимум 5 кейсов — ограничение шаблона отчета", 'error');
      return;
    }
    setAuditData(prev => ({
      ...prev,
      cases: [...prev.cases, {
        title: 'Новый кейс', vulnerability: '', risk: '', recommendation: '',
        priority: 'ТРЕТИЙ ПРИОРИТЕТ', category: categories[0] || '',
        image_prompt: '', image_b64: null,
      }]
    }));
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
        updateCase(index, { image_b64: data.image_b64, imageGenerating: false, image_reusable: true, image_source: 'generated' });
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
      data.cases = data.cases.map(c => ({ ...c, category: stripCategoryNumber(c.category) }));
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
    // Форму нового аудитора могли заполнить, но не нажать «Сохранить» — дожимаем сами
    let auditor = auditors.find(a => a.id === auditorId) || null;
    if (!auditor && newAuditor?.name?.trim()) {
      auditor = await handleSaveAuditor();
    }
    try {
      const res = await fetch(`${API}/api/generate_pptx`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          data: {
            ...auditData,
            cases: auditData.cases.map(({ suggestions, suggIdx, imageGenerating, textRevising, image_source, categoryCustom, ...c }) => c)
          },
          audit_type: auditType,
          save_to_memory: saveToMemory,
          auditor
        })
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

          <div className="input-group">
            <label>Кто делает аудит (имя и фото попадут в отчет)</label>
            <div className="auditor-row">
              {auditors.find(a => a.id === auditorId)?.photo_b64 && (
                <img className="auditor-avatar" src={auditors.find(a => a.id === auditorId).photo_b64} alt="" />
              )}
              <select
                value={newAuditor ? '__new__' : auditorId}
                onChange={e => {
                  if (e.target.value === '__new__') {
                    setNewAuditor({ name: '', photo_b64: null });
                  } else {
                    setNewAuditor(null);
                    setAuditorId(e.target.value);
                  }
                }}
              >
                <option value="">— не указывать —</option>
                {auditors.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                <option value="__new__">+ Добавить нового аудитора</option>
              </select>
            </div>

            {newAuditor && (
              <div className="auditor-new">
                <input
                  placeholder="Фамилия Имя"
                  value={newAuditor.name}
                  onChange={e => setNewAuditor({ ...newAuditor, name: e.target.value })}
                />
                <label className="btn-small auditor-photo-btn">
                  {newAuditor.photo_b64 ? "✓ Фото выбрано" : "📷 Фото"}
                  <input
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={e => {
                      const file = e.target.files?.[0];
                      if (file) openPhotoCrop(file);
                      e.target.value = "";
                    }}
                  />
                </label>
                <button className="btn-small" onClick={handleSaveAuditor}>Сохранить</button>
                <button className="btn-small" onClick={() => setNewAuditor(null)}>✕</button>
              </div>
            )}
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
          <div className="flex-between" style={{marginBottom: '2rem'}}>
            <h2>Предпросмотр: {auditData.client_name}</h2>
            <div style={{display: 'flex', gap: '0.5rem'}}>
              <button className="btn" onClick={() => setStep(1)} style={{background: 'transparent', border: '1px solid var(--border-glass)', color: 'var(--text-main)'}}>Назад</button>
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

          <div className="flex-between" style={{marginTop: '1rem'}}>
            <h3>Кейсы ({auditData.cases.length})</h3>
            {auditData.cases.length < 5 && (
              <button className="btn-small" onClick={handleAddCase}>＋ Добавить кейс</button>
            )}
          </div>
          <div className="cases-grid">
            {auditData.cases.map((c, i) => (
              <div key={i} className="glass-panel case-card" style={{padding: '1.5rem'}}>
                <div className="flex-between">
                  <h4>Кейс {i+1}</h4>
                  <div style={{display: 'flex', alignItems: 'center', gap: '0.5rem'}}>
                    <span className={`badge ${c.priority === 'ПЕРВЫЙ ПРИОРИТЕТ' ? 'red' : c.priority === 'ВТОРОЙ ПРИОРИТЕТ' ? 'orange' : 'cyan'}`}>
                      {c.priority}
                    </span>
                    <button className="btn-small" title="Удалить кейс" onClick={() => handleDeleteCase(i)}>✕</button>
                  </div>
                </div>

                <TextareaAutosize value={c.title} onChange={e => handleCaseChange(i, 'title', e.target.value)} minRows={2} />
                {categories.includes(c.category) && !c.categoryCustom ? (
                  <select
                    value={c.category}
                    onChange={e => {
                      if (e.target.value === '__custom__') {
                        updateCase(i, { categoryCustom: true });
                      } else {
                        handleCaseChange(i, 'category', e.target.value);
                      }
                    }}
                    style={{width: '100%', marginBottom: '1rem'}}
                  >
                    {categories.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                    <option value="__custom__">✏️ Своя категория…</option>
                  </select>
                ) : (
                  <div style={{display: 'flex', gap: '0.5rem', marginBottom: '1rem'}}>
                    <input
                      value={c.category}
                      autoFocus={!!c.categoryCustom}
                      onChange={e => handleCaseChange(i, 'category', e.target.value)}
                      placeholder="Название раздела (без номера)..."
                      style={{flex: 1}}
                    />
                    <button className="btn-small" title="Сохранить категорию — станет доступна во всех кейсах" onClick={() => handleSaveCategory(i)}>💾</button>
                    <button className="btn-small" title="Выбрать из списка" onClick={() => {
                      updateCase(i, { category: categories.includes(c.category) ? c.category : (categories[0] || ''), categoryCustom: false });
                    }}>▾</button>
                  </div>
                )}

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
                      <div className="image-actions">
                        <button className="btn" style={{padding: '0.5rem 1rem', fontSize: '0.9rem'}} onClick={() => handleRegenerateImage(i)}>
                          {c.image_b64 ? "🎨 Сгенерировать" : "Сгенерировать"}
                        </button>
                        <label className="btn btn-upload" style={{padding: '0.5rem 1rem', fontSize: '0.9rem'}}>
                          📁 Загрузить
                          <input type="file" accept="image/*" hidden onChange={e => {
                            handleUploadImage(i, e.target.files?.[0]);
                            e.target.value = "";
                          }} />
                        </label>
                      </div>
                    </div>
                  )}

                  {!c.imageGenerating && c.suggestions?.length > 1 && c.image_source === 'library' && (
                    <>
                      <button className="suggestion-arrow left" onClick={() => cycleSuggestion(i, -1)}>‹</button>
                      <button className="suggestion-arrow right" onClick={() => cycleSuggestion(i, 1)}>›</button>
                      <span className="suggestion-counter">{(c.suggIdx ?? 0) + 1}/{c.suggestions.length} из библиотеки</span>
                    </>
                  )}
                </div>

                {c.image_source === 'uploaded' && (
                  <label className="reuse-checkbox">
                    <input
                      type="checkbox"
                      checked={!!c.image_reusable}
                      onChange={e => handleCaseChange(i, 'image_reusable', e.target.checked)}
                    />
                    <span>Это иллюстрация — сохранить в библиотеку для будущих аудитов (фотографии объектов не сохраняем)</span>
                  </label>
                )}

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
            <div className="action-bar" style={{marginBottom: '1rem'}}>
              <span className="style-select-wrap">
                <label style={{fontSize: '0.9rem'}}>Стиль картинок:</label>
                <select value={imageStyle} onChange={e => setImageStyle(e.target.value)}>
                  {IMAGE_STYLES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </span>
              <button className="btn btn-action" onClick={handleGenerateAllImages} disabled={loading || revising || !!batchProgress}>
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
              <button className="btn btn-download" onClick={handleGeneratePptx} disabled={loading || revising}>
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

      {photoCrop && (
        <div className="crop-backdrop">
          <div className="crop-modal glass-panel">
            <h3>Кадрирование фото</h3>
            <p style={{fontSize: '0.85rem', color: 'var(--text-muted)', margin: '0.5rem 0 1rem'}}>
              Перетащите фото и подберите масштаб — в отчет попадет выделенная область.
            </p>
            <div
              className="crop-viewport"
              onPointerDown={e => {
                cropDragRef.current = { sx: e.clientX, sy: e.clientY, ox: photoCrop.x, oy: photoCrop.y };
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerMove={e => {
                if (!cropDragRef.current) return;
                const d = cropDragRef.current;
                setPhotoCrop(c => clampCrop({ ...c, x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy }));
              }}
              onPointerUp={() => { cropDragRef.current = null; }}
            >
              <img
                src={photoCrop.src}
                draggable={false}
                alt=""
                style={{
                  width: photoCrop.nw * photoCrop.scale,
                  height: photoCrop.nh * photoCrop.scale,
                  transform: `translate(${photoCrop.x}px, ${photoCrop.y}px)`
                }}
              />
              <div className="crop-mask"></div>
            </div>
            <input
              type="range"
              min={photoCrop.minScale}
              max={photoCrop.minScale * 4}
              step="0.01"
              value={photoCrop.scale}
              onChange={e => cropZoom(parseFloat(e.target.value))}
              style={{marginTop: '1rem'}}
            />
            <div style={{display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem'}}>
              <button className="btn-small" onClick={() => setPhotoCrop(null)}>Отмена</button>
              <button className="btn" style={{padding: '0.5rem 1.5rem', fontSize: '0.95rem'}} onClick={applyCrop}>Готово</button>
            </div>
          </div>
        </div>
      )}

      <footer className="site-footer">
        Разработка: Lexx · <a href="mailto:deuslevolt013@gmail.com">deuslevolt013@gmail.com</a>
      </footer>

      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>{t.message}</div>
        ))}
      </div>
    </div>
  )
}

export default App

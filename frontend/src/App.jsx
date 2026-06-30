import { useState } from 'react'

function App() {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [auditType, setAuditType] = useState('express');
  const [formData, setFormData] = useState({
    general_data: '',
    vulnerabilities: '',
    conclusions: ''
  });
  const [auditData, setAuditData] = useState(null);
  
  const vulnSuggestions = [
    "Отсутствует резервное копирование (бэкапы)",
    "Нет антивирусной защиты",
    "Использование пиратского ПО (Windows, Office)",
    "Открыты порты RDP наружу",
    "Сетевое оборудование без паролей (admin/admin)",
    "Серверная в плачевном состоянии (пыль, перегрев)",
    "Старое железо, жесткие диски (HDD) сыпятся"
  ];

  const handleParse = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...formData, audit_type: auditType })
      });
      const data = await res.json();
      setAuditData(data);
      setStep(2);
    } catch (err) {
      alert("Ошибка при парсинге: " + err);
    }
    setLoading(false);
  };

  const handleCaseChange = (index, field, value) => {
    const newData = { ...auditData };
    newData.cases[index][field] = value;
    setAuditData(newData);
  };

  const handleRegenerateImage = async (index) => {
    const caseObj = auditData.cases[index];
    if (!caseObj.image_prompt) return;
    
    // Set loading state for this specific image somehow, 
    // or just a global block
    const newData = { ...auditData };
    newData.cases[index].image_b64 = "loading";
    setAuditData(newData);
    
    try {
      const res = await fetch('http://localhost:8000/api/generate_image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: caseObj.image_prompt })
      });
      const data = await res.json();
      const finalData = { ...auditData };
      finalData.cases[index].image_b64 = data.image_b64;
      setAuditData(finalData);
    } catch (err) {
      alert("Ошибка генерации картинки: " + err);
      const finalData = { ...auditData };
      finalData.cases[index].image_b64 = null;
      setAuditData(finalData);
    }
  };

  const handleGeneratePptx = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/generate_pptx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: auditData })
      });
      const data = await res.json();
      if (data.url) {
        window.open(data.url, '_blank');
      }
    } catch (err) {
      alert("Ошибка создания PPTX: " + err);
    }
    setLoading(false);
  };

  return (
    <div className="container">
      <h1 className="title">Audit Generator AI</h1>
      
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
            <textarea 
              value={formData.general_data}
              onChange={e => setFormData({...formData, general_data: e.target.value})}
              placeholder="Например: ТОО Ромашка, 100 сотрудников..."
            />
          </div>

          <div className="input-group">
            <label>Выявленные уязвимости</label>
            <textarea 
              value={formData.vulnerabilities}
              onChange={e => setFormData({...formData, vulnerabilities: e.target.value})}
              placeholder="Опишите все проблемы своими словами..."
              style={{minHeight: '200px'}}
            />
            <div style={{marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--text-muted)'}}>
              Подсказки: {vulnSuggestions.map((s, i) => (
                <span key={i} style={{cursor:'pointer', borderBottom:'1px dashed', marginRight:'10px'}}
                      onClick={() => setFormData(f => ({...f, vulnerabilities: f.vulnerabilities + s + '\n'}))}>
                  {s}
                </span>
              ))}
            </div>
          </div>

          <div className="input-group">
            <label>Заключение / Выводы</label>
            <textarea 
              value={formData.conclusions}
              onChange={e => setFormData({...formData, conclusions: e.target.value})}
              placeholder="Итоговые предложения..."
            />
          </div>

          <button className="btn" onClick={handleParse} disabled={loading}>
            {loading ? <div className="loader"></div> : "Сгенерировать структуру"}
          </button>
        </div>
      )}

      {step === 2 && auditData && (
        <div className="glass-panel">
          <div className="flex-between" style={{marginBottom: '2rem'}}>
            <h2>Предпросмотр: {auditData.client_name}</h2>
            <button className="btn" onClick={() => setStep(1)} style={{background: 'transparent', border: '1px solid var(--border-glass)'}}>Назад</button>
          </div>

          <div className="input-group">
            <label>Текст обзора (слайд 2)</label>
            <textarea 
              value={auditData.review}
              onChange={e => setAuditData({...auditData, review: e.target.value})}
              style={{minHeight: '80px'}}
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
                
                <input value={c.title} onChange={e => handleCaseChange(i, 'title', e.target.value)} />
                <select value={c.category} onChange={e => handleCaseChange(i, 'category', e.target.value)}>
                  <option value="I. Серверная инфраструктура">I. Серверная инфраструктура</option>
                  <option value="II. Сеть и ИТ-поддержка">II. Сеть и ИТ-поддержка</option>
                </select>
                
                <label style={{fontSize: '0.85rem'}}>Уязвимость:</label>
                <textarea value={c.vulnerability} onChange={e => handleCaseChange(i, 'vulnerability', e.target.value)} style={{minHeight: '60px'}}/>
                
                <label style={{fontSize: '0.85rem'}}>Риски:</label>
                <textarea value={c.risk} onChange={e => handleCaseChange(i, 'risk', e.target.value)} style={{minHeight: '60px'}}/>
                
                {auditType === 'full' && (
                  <>
                    <label style={{fontSize: '0.85rem'}}>Рекомендации:</label>
                    <textarea value={c.recommendation || ''} onChange={e => handleCaseChange(i, 'recommendation', e.target.value)} style={{minHeight: '60px'}}/>
                  </>
                )}

                <div className="case-image-wrap">
                  {c.image_b64 === 'loading' ? (
                    <div style={{display:'flex',height:'100%',alignItems:'center',justifyContent:'center'}}>
                      <div className="loader"></div>
                    </div>
                  ) : c.image_b64 ? (
                    <img src={c.image_b64} alt="Case visual" />
                  ) : (
                    <div style={{display:'flex',height:'100%',alignItems:'center',justifyContent:'center', color: 'var(--text-muted)', textAlign: 'center', padding: '1rem'}}>
                      Нет картинки.<br/>Промпт: {c.image_prompt}
                    </div>
                  )}
                  
                  <div className="case-image-overlay">
                    <button className="btn" style={{padding: '0.5rem 1rem', fontSize: '0.9rem'}} onClick={() => handleRegenerateImage(i)}>
                      {c.image_b64 ? "Перегенерировать" : "Сгенерировать"}
                    </button>
                  </div>
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

          <div style={{marginTop: '3rem', textAlign: 'center'}}>
            <button className="btn" onClick={handleGeneratePptx} disabled={loading} style={{fontSize: '1.25rem', padding: '1rem 3rem'}}>
              {loading ? <div className="loader"></div> : "💾 Скачать PPTX Отчет"}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App

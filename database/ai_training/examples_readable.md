# Примеры учебных нарядов

Все данные вымышлены. Реальных фотографий здесь нет.

## SYN-85833c2c17fa429b845d11a1c49fd58b — validation

Вход (без ответа):

```json
{
  "equipment": {
    "category": "Дробильное оборудование",
    "criticality": "critical",
    "id": "SYN-b5d948b1372e434f979fdd6c5243ad51",
    "inventory_number": "SYN-INV-0024",
    "model": "Учебная модель U-024",
    "name": "Дробильное оборудование — учебный объект 24",
    "site_id": "SYN-fbd9f99947a1452fa73df709f85b7d03"
  },
  "history": [],
  "material_catalog": [
    {
      "id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
      "manufacturer": "SKF",
      "model": "LGMT 2",
      "name": "Смазка подшипниковая SKF LGMT 2",
      "unit": "кг"
    },
    {
      "id": "SYN-f9738cbca6ef46ef93eb005e9bbc22bf",
      "manufacturer": "SKF",
      "model": "6307",
      "name": "Подшипник шариковый радиальный 6307",
      "unit": "шт"
    }
  ],
  "material_usage": [
    {
      "id": "SYN-dbdf8cd04fe94c87a227af36ec84c7a0",
      "material_id": "SYN-f9738cbca6ef46ef93eb005e9bbc22bf",
      "quantity": 1,
      "report_id": "SYN-f2e7bd9d03d44a4fb9d92be007eb1aad",
      "unit": "шт",
      "work_order_id": "SYN-85833c2c17fa429b845d11a1c49fd58b"
    },
    {
      "id": "SYN-a7ae246d155f44e085f06d01716f542f",
      "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
      "quantity": 0.3,
      "report_id": "SYN-f2e7bd9d03d44a4fb9d92be007eb1aad",
      "unit": "кг",
      "work_order_id": "SYN-85833c2c17fa429b845d11a1c49fd58b"
    }
  ],
  "photo_evidence": [
    {
      "attachment_present": true,
      "captured_at": "2026-07-09T16:50:00+05:00",
      "content_origin": "simulated_metadata_only",
      "equipment_id": "SYN-b5d948b1372e434f979fdd6c5243ad51",
      "id": "SYN-e9c2056485a04e22bd1a7a5bb7c231b3",
      "image_available": false,
      "phase": "after",
      "report_id": "SYN-f2e7bd9d03d44a4fb9d92be007eb1aad",
      "work_order_id": "SYN-85833c2c17fa429b845d11a1c49fd58b"
    }
  ],
  "question": "Можно ли закрыть этот учебный наряд? Укажи итог и объясни его по фактам.",
  "report": {
    "comment": "Результат требует проверки мастером; данные учебные.",
    "fault_code": "APP-03",
    "id": "SYN-f2e7bd9d03d44a4fb9d92be007eb1aad",
    "performed_work": "Обследован узел SYN-INV-0024, оформлены наблюдения по опоре. После работ по карте результат контрольной проверки внесён в журнал. Запись передана мастеру для проверки.",
    "submitted_at": "2026-07-09T16:51:00+05:00",
    "work_order_id": "SYN-85833c2c17fa429b845d11a1c49fd58b"
  },
  "shift": {
    "date": "2026-07-09",
    "ends_at": "2026-07-09T23:00:00+05:00",
    "id": "SYN-89d364d24030477fba6267c4f7707df0",
    "shift_code": "late",
    "site_id": null,
    "starts_at": "2026-07-09T15:00:00+05:00"
  },
  "work_norm": {
    "equipment_category": "Дробильное оборудование",
    "expected_materials": [
      {
        "material_id": "SYN-767f77343e3e4c8baa9043ab3ed31be7",
        "quantity": 1,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      },
      {
        "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
        "quantity": 0.3,
        "tolerance_ratio": 0.25,
        "unit": "кг"
      }
    ],
    "expected_minutes": 90,
    "fault_code": "APP-03",
    "id": "SYN-455f28fcb9cf4f30b52b7e220bde26e6",
    "name": "Обследование заявленной вибрации дробильного узла",
    "tolerance_ratio": 0.25
  },
  "work_order": {
    "accepted_at": "2026-07-09T15:28:00+05:00",
    "due_at": "2026-07-09T17:49:00+05:00",
    "equipment_id": "SYN-b5d948b1372e434f979fdd6c5243ad51",
    "expected_materials": [
      {
        "material_id": "SYN-f9738cbca6ef46ef93eb005e9bbc22bf",
        "quantity": 1,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      },
      {
        "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
        "quantity": 0.3,
        "tolerance_ratio": 0.25,
        "unit": "кг"
      }
    ],
    "fault_code": "APP-03",
    "id": "SYN-85833c2c17fa429b845d11a1c49fd58b",
    "issued_at": "2026-07-09T15:27:00+05:00",
    "kind": "unplanned",
    "number": "SYN-2026-0008",
    "priority": "normal",
    "problem_description": "Для SYN-INV-0024 заявлен рост вибрации. Требуются диагностика причины и документирование результата. Отразить фактический расход материалов.",
    "reported_at": "2026-07-09T16:51:00+05:00",
    "required_actions": [
      "Описать результаты диагностики.",
      "Зарегистрировать контроль состояния после согласованных работ."
    ],
    "shift_id": "SYN-89d364d24030477fba6267c4f7707df0",
    "site_id": "SYN-fbd9f99947a1452fa73df709f85b7d03",
    "started_at": "2026-07-09T15:31:00+05:00",
    "title": "Обследование заявленной вибрации дробильного узла",
    "work_norm_id": "SYN-455f28fcb9cf4f30b52b7e220bde26e6"
  }
}
```

Учебный ответ:

```json
{
  "issues": [],
  "manual_review_required": true,
  "photo_verdict": "not_assessed",
  "reasons": [
    "Текстовая полнота, учебный расход и сроки соответствуют заданным правилам; фото не оценивалось."
  ],
  "verdict": "accepted"
}
```

## SYN-e449e1d22a6e451bb58f7406f7ed17d3 — train

Вход (без ответа):

```json
{
  "equipment": {
    "category": "Электрооборудование",
    "criticality": "high",
    "id": "SYN-a8d95e5c196841b291bc642f63726923",
    "inventory_number": "SYN-INV-0053",
    "model": "Учебная модель U-053",
    "name": "Электрооборудование — учебный объект 53",
    "site_id": "SYN-b59a0602acc7444c884301f24f735a44"
  },
  "history": [],
  "material_catalog": [
    {
      "id": "SYN-730c2f316ac44659a65fc6c129fe2a96",
      "manufacturer": null,
      "model": null,
      "name": "Кабель учебной контрольной цепи",
      "unit": "м"
    },
    {
      "id": "SYN-75154090b0c14052b179674297e23c9a",
      "manufacturer": null,
      "model": null,
      "name": "Клемма учебной контрольной цепи",
      "unit": "шт"
    }
  ],
  "material_usage": [
    {
      "id": "SYN-60dc54ddf28748fd8a33a817dc86b7ee",
      "material_id": "SYN-730c2f316ac44659a65fc6c129fe2a96",
      "quantity": 3,
      "report_id": "SYN-17af9691fd6644cfba4f48b19acb4166",
      "unit": "м",
      "work_order_id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3"
    },
    {
      "id": "SYN-5d0f332fab9042638df98a48e117db0b",
      "material_id": "SYN-75154090b0c14052b179674297e23c9a",
      "quantity": 4,
      "report_id": "SYN-17af9691fd6644cfba4f48b19acb4166",
      "unit": "шт",
      "work_order_id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3"
    }
  ],
  "photo_evidence": [
    {
      "attachment_present": true,
      "captured_at": "2026-07-08T07:13:00+05:00",
      "content_origin": "simulated_metadata_only",
      "equipment_id": "SYN-a8d95e5c196841b291bc642f63726923",
      "id": "SYN-add1fa8677264201a59c68f1aa5d35d7",
      "image_available": false,
      "phase": "before",
      "report_id": null,
      "work_order_id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3"
    },
    {
      "attachment_present": true,
      "captured_at": "2026-07-08T08:16:00+05:00",
      "content_origin": "simulated_metadata_only",
      "equipment_id": "SYN-a8d95e5c196841b291bc642f63726923",
      "id": "SYN-32f1f623d99b4d098f8bf2b9e1aaf257",
      "image_available": false,
      "phase": "after",
      "report_id": "SYN-17af9691fd6644cfba4f48b19acb4166",
      "work_order_id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3"
    }
  ],
  "question": "Можно ли закрыть этот учебный наряд? Укажи итог и объясни его по фактам.",
  "report": {
    "comment": "Результат требует проверки мастером; данные учебные.",
    "fault_code": "APP-19",
    "id": "SYN-17af9691fd6644cfba4f48b19acb4166",
    "performed_work": "У SYN-INV-0053 проверена учебная контрольная цепь. Описан дефект соединения, согласованные работы выполнены. Результат контрольной проверки зарегистрирован: сигнал устойчив. Использованные материалы отражены отдельно.",
    "submitted_at": "2026-07-08T08:17:00+05:00",
    "work_order_id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3"
  },
  "shift": {
    "date": "2026-07-08",
    "ends_at": "2026-07-08T15:00:00+05:00",
    "id": "SYN-14f1c17ab00b4fe6841e443cbc192ae0",
    "shift_code": "day",
    "site_id": null,
    "starts_at": "2026-07-08T07:00:00+05:00"
  },
  "work_norm": {
    "equipment_category": "Электрооборудование",
    "expected_materials": [
      {
        "material_id": "SYN-730c2f316ac44659a65fc6c129fe2a96",
        "quantity": 3,
        "tolerance_ratio": 0.25,
        "unit": "м"
      },
      {
        "material_id": "SYN-75154090b0c14052b179674297e23c9a",
        "quantity": 4,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      }
    ],
    "expected_minutes": 60,
    "fault_code": "APP-19",
    "id": "SYN-04cdc8b829844317a78e48f7c3df310b",
    "name": "Проверка учебной контрольной цепи",
    "tolerance_ratio": 0.25
  },
  "work_order": {
    "accepted_at": "2026-07-08T07:15:00+05:00",
    "due_at": "2026-07-08T07:56:00+05:00",
    "equipment_id": "SYN-a8d95e5c196841b291bc642f63726923",
    "expected_materials": [
      {
        "material_id": "SYN-730c2f316ac44659a65fc6c129fe2a96",
        "quantity": 3,
        "tolerance_ratio": 0.25,
        "unit": "м"
      },
      {
        "material_id": "SYN-75154090b0c14052b179674297e23c9a",
        "quantity": 4,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      }
    ],
    "fault_code": "APP-19",
    "id": "SYN-e449e1d22a6e451bb58f7406f7ed17d3",
    "issued_at": "2026-07-08T07:13:00+05:00",
    "kind": "unplanned",
    "number": "SYN-2026-0005",
    "priority": "emergency",
    "problem_description": "На SYN-INV-0053 заявлен пропадающий учебный сигнал. Требуется диагностика контрольной цепи и запись результата. Наблюдения и ограничения проверки записать в отчёт.",
    "reported_at": "2026-07-08T08:17:00+05:00",
    "required_actions": [
      "Описать установленную причину нестабильного сигнала.",
      "Зафиксировать выполненные работы и результат проверки."
    ],
    "shift_id": "SYN-14f1c17ab00b4fe6841e443cbc192ae0",
    "site_id": "SYN-b59a0602acc7444c884301f24f735a44",
    "started_at": "2026-07-08T07:16:00+05:00",
    "title": "Проверка учебной контрольной цепи",
    "work_norm_id": "SYN-04cdc8b829844317a78e48f7c3df310b"
  }
}
```

Учебный ответ:

```json
{
  "issues": [
    {
      "code": "overdue",
      "evidence_fields": [
        "work_orders.due_at",
        "reports.submitted_at"
      ],
      "explanation": "Отчёт передан позже срока, заданного мастером.",
      "severity": "remarks"
    }
  ],
  "manual_review_required": true,
  "photo_verdict": "not_assessed",
  "reasons": [
    "Отчёт передан позже срока, заданного мастером."
  ],
  "verdict": "accepted_with_remarks"
}
```

## SYN-dcb65c0db8f7448da81874f530a4f3cd — train

Вход (без ответа):

```json
{
  "equipment": {
    "category": "Конвейер",
    "criticality": "medium",
    "id": "SYN-f6c03c11053643d49ec1f58b0a127d71",
    "inventory_number": "SYN-INV-0009",
    "model": "Учебная модель U-009",
    "name": "Конвейер — учебный объект 09",
    "site_id": "SYN-3d77683b704748748b9c6ab04accd89d"
  },
  "history": [],
  "material_catalog": [
    {
      "id": "SYN-a9e156cda84949df8dac84473da38d33",
      "manufacturer": "SKF",
      "model": "6204",
      "name": "Подшипник шариковый радиальный 6204",
      "unit": "шт"
    },
    {
      "id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
      "manufacturer": "SKF",
      "model": "LGMT 2",
      "name": "Смазка подшипниковая SKF LGMT 2",
      "unit": "кг"
    }
  ],
  "material_usage": [
    {
      "id": "SYN-fa698a37d5754affaf7b071eadd02469",
      "material_id": "SYN-a9e156cda84949df8dac84473da38d33",
      "quantity": 1,
      "report_id": "SYN-edffbfbcac1641839a9e8b287d5f695d",
      "unit": "шт",
      "work_order_id": "SYN-dcb65c0db8f7448da81874f530a4f3cd"
    },
    {
      "id": "SYN-14ebd92d1699478f9052810eab9bda3d",
      "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
      "quantity": 0.15,
      "report_id": "SYN-edffbfbcac1641839a9e8b287d5f695d",
      "unit": "кг",
      "work_order_id": "SYN-dcb65c0db8f7448da81874f530a4f3cd"
    }
  ],
  "photo_evidence": [
    {
      "attachment_present": true,
      "captured_at": "2026-07-08T07:16:00+05:00",
      "content_origin": "simulated_metadata_only",
      "equipment_id": "SYN-f6c03c11053643d49ec1f58b0a127d71",
      "id": "SYN-4c55980067c04ad3b23a83ed290d831c",
      "image_available": false,
      "phase": "before",
      "report_id": null,
      "work_order_id": "SYN-dcb65c0db8f7448da81874f530a4f3cd"
    },
    {
      "attachment_present": true,
      "captured_at": "2026-07-08T08:45:00+05:00",
      "content_origin": "simulated_metadata_only",
      "equipment_id": "SYN-f6c03c11053643d49ec1f58b0a127d71",
      "id": "SYN-0077868840d145eaa8cca95ea69597e1",
      "image_available": false,
      "phase": "after",
      "report_id": "SYN-edffbfbcac1641839a9e8b287d5f695d",
      "work_order_id": "SYN-dcb65c0db8f7448da81874f530a4f3cd"
    }
  ],
  "question": "Можно ли закрыть этот учебный наряд? Укажи итог и объясни его по фактам.",
  "report": {
    "comment": "Результат требует проверки мастером; данные учебные.",
    "fault_code": "APP-01",
    "id": "SYN-edffbfbcac1641839a9e8b287d5f695d",
    "performed_work": "Проверил, ок.",
    "submitted_at": "2026-07-08T08:46:00+05:00",
    "work_order_id": "SYN-dcb65c0db8f7448da81874f530a4f3cd"
  },
  "shift": {
    "date": "2026-07-08",
    "ends_at": "2026-07-08T15:00:00+05:00",
    "id": "SYN-14f1c17ab00b4fe6841e443cbc192ae0",
    "shift_code": "day",
    "site_id": null,
    "starts_at": "2026-07-08T07:00:00+05:00"
  },
  "work_norm": {
    "equipment_category": "Конвейер",
    "expected_materials": [
      {
        "material_id": "SYN-2d53db634a3e489ba407af2ce57b1a67",
        "quantity": 1,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      },
      {
        "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
        "quantity": 0.15,
        "tolerance_ratio": 0.25,
        "unit": "кг"
      }
    ],
    "expected_minutes": 95,
    "fault_code": "APP-01",
    "id": "SYN-5014453b1fda47cfa4b2ddefe0689b55",
    "name": "Диагностика подшипникового узла конвейера",
    "tolerance_ratio": 0.25
  },
  "work_order": {
    "accepted_at": "2026-07-08T07:19:00+05:00",
    "due_at": "2026-07-08T09:46:00+05:00",
    "equipment_id": "SYN-f6c03c11053643d49ec1f58b0a127d71",
    "expected_materials": [
      {
        "material_id": "SYN-a9e156cda84949df8dac84473da38d33",
        "quantity": 1,
        "tolerance_ratio": 0.25,
        "unit": "шт"
      },
      {
        "material_id": "SYN-c1c4b5a4bd934514b9a19b6405f56197",
        "quantity": 0.15,
        "tolerance_ratio": 0.25,
        "unit": "кг"
      }
    ],
    "fault_code": "APP-01",
    "id": "SYN-dcb65c0db8f7448da81874f530a4f3cd",
    "issued_at": "2026-07-08T07:16:00+05:00",
    "kind": "unplanned",
    "number": "SYN-2026-0001",
    "priority": "high",
    "problem_description": "По SYN-INV-0009 поступила заявка: шум и нагрев учебной опоры выше обычного наблюдаемого состояния. Результат передать мастеру смены.",
    "reported_at": "2026-07-08T08:46:00+05:00",
    "required_actions": [
      "Уточнить причину заявленного шума.",
      "Документировать состояние опоры после согласованных работ."
    ],
    "shift_id": "SYN-14f1c17ab00b4fe6841e443cbc192ae0",
    "site_id": "SYN-3d77683b704748748b9c6ab04accd89d",
    "started_at": "2026-07-08T07:23:00+05:00",
    "title": "Диагностика подшипникового узла конвейера",
    "work_norm_id": "SYN-5014453b1fda47cfa4b2ddefe0689b55"
  }
}
```

Учебный ответ:

```json
{
  "issues": [
    {
      "code": "empty_report",
      "evidence_fields": [
        "reports.performed_work"
      ],
      "explanation": "Описание выполненных работ не содержит проверяемых действий и результата.",
      "severity": "rework"
    }
  ],
  "manual_review_required": true,
  "photo_verdict": "not_assessed",
  "reasons": [
    "Описание выполненных работ не содержит проверяемых действий и результата."
  ],
  "verdict": "rework_required"
}
```

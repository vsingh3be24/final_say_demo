# Semantic model validation and holdout results

> This is a small generated-fixture diagnostic, not a real-world accuracy
> estimate. The `two_annotator_kappa` value is computed from deterministic seed
> labels, not independent human annotations. The `nli` and `prompted_llm`
> comparisons below are heuristic baselines, not external model calls. See the
> [project report](FINAL-PROJECT-REPORT.md) for the limitations and live-system
> evidence.

```json
{
  "model": "semantic-nli-deberta-v3-small",
  "candidate_threshold": 0.2,
  "confidence_threshold": 0.2,
  "threshold_selection": {
    "validation_pairs": 30,
    "retrieval_precision_at_selected_threshold": 0.5333333333333333,
    "validation_macro_f1": 0.8095238095238094,
    "validation_institutions": [
      "northgate",
      "riverside"
    ]
  },
  "validation": {
    "count": 30,
    "accuracy": 0.8666666666666667,
    "macro_precision": 0.7857142857142857,
    "macro_recall": 0.8571428571428571,
    "macro_f1": 0.8095238095238094,
    "per_class_f1": {
      "consistent": 1.0,
      "contradictory": 0.6666666666666666,
      "superseded": 1.0,
      "corrected": 1.0,
      "extended": 0.0,
      "cancelled": 1.0,
      "unresolved": 1.0
    },
    "confusion_matrix": [
      [
        4,
        0,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        4,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        6,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        0,
        4,
        0,
        0,
        0
      ],
      [
        0,
        4,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        0,
        0,
        0,
        4,
        0
      ],
      [
        0,
        0,
        0,
        0,
        0,
        0,
        4
      ]
    ],
    "false_confirmation_rate": 0.0,
    "unresolved_rate": 0.13333333333333333,
    "candidate_recall_at_1": 0.5333333333333333,
    "candidate_coverage": 1.0,
    "median_latency_ms": 48.124333494342864,
    "labels": {
      "gold": [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "superseded",
        "superseded"
      ],
      "predicted": [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "superseded",
        "superseded"
      ]
    }
  },
  "temporal": {
    "count": 21,
    "accuracy": 0.42857142857142855,
    "macro_precision": 0.25,
    "macro_recall": 0.42857142857142855,
    "macro_f1": 0.2952380952380952,
    "per_class_f1": {
      "consistent": 0.0,
      "contradictory": 0.4,
      "superseded": 1.0,
      "corrected": 0.0,
      "extended": 0.0,
      "cancelled": 0.0,
      "unresolved": 0.6666666666666666
    },
    "confusion_matrix": [
      [
        0,
        0,
        0,
        0,
        0,
        0,
        3
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        3,
        0,
        0,
        0,
        0
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        0,
        0,
        0,
        0,
        3
      ]
    ],
    "false_confirmation_rate": 0.0,
    "unresolved_rate": 0.2857142857142857,
    "candidate_recall_at_1": 0.47619047619047616,
    "candidate_coverage": 1.0,
    "median_latency_ms": 46.45754201919772,
    "labels": {
      "gold": [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved"
      ],
      "predicted": [
        "unresolved",
        "contradictory",
        "superseded",
        "contradictory",
        "contradictory",
        "contradictory",
        "unresolved",
        "unresolved",
        "contradictory",
        "superseded",
        "contradictory",
        "contradictory",
        "contradictory",
        "unresolved",
        "unresolved",
        "contradictory",
        "superseded",
        "contradictory",
        "contradictory",
        "contradictory",
        "unresolved"
      ]
    }
  },
  "institution": {
    "count": 21,
    "accuracy": 0.7142857142857143,
    "macro_precision": 0.7321428571428571,
    "macro_recall": 0.7142857142857143,
    "macro_f1": 0.6860853432282003,
    "per_class_f1": {
      "consistent": 0.8,
      "contradictory": 0.5454545454545454,
      "superseded": 1.0,
      "corrected": 0.8,
      "extended": 0.0,
      "cancelled": 0.8,
      "unresolved": 0.8571428571428571
    },
    "confusion_matrix": [
      [
        2,
        0,
        0,
        0,
        0,
        0,
        1
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        0,
        3,
        0,
        0,
        0,
        0
      ],
      [
        0,
        1,
        0,
        2,
        0,
        0,
        0
      ],
      [
        0,
        3,
        0,
        0,
        0,
        0,
        0
      ],
      [
        0,
        1,
        0,
        0,
        0,
        2,
        0
      ],
      [
        0,
        0,
        0,
        0,
        0,
        0,
        3
      ]
    ],
    "false_confirmation_rate": 0.0,
    "unresolved_rate": 0.19047619047619047,
    "candidate_recall_at_1": 0.42857142857142855,
    "candidate_coverage": 1.0,
    "median_latency_ms": 44.835500011686236,
    "labels": {
      "gold": [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "extended",
        "cancelled",
        "unresolved"
      ],
      "predicted": [
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "consistent",
        "contradictory",
        "superseded",
        "corrected",
        "contradictory",
        "cancelled",
        "unresolved",
        "unresolved",
        "contradictory",
        "superseded",
        "contradictory",
        "contradictory",
        "contradictory",
        "unresolved"
      ]
    }
  },
  "two_annotator_kappa": 0.625,
  "baselines": {
    "temporal": {
      "mock": {
        "accuracy": 0.14285714285714285,
        "macro_f1": 0.05714285714285715,
        "unresolved_rate": 0.42857142857142855
      },
      "chronological": {
        "accuracy": 0.2857142857142857,
        "macro_f1": 0.14285714285714285,
        "unresolved_rate": 0.0
      },
      "page_change": {
        "accuracy": 0.14285714285714285,
        "macro_f1": 0.03571428571428571,
        "unresolved_rate": 0.0
      },
      "nli": {
        "accuracy": 0.2857142857142857,
        "macro_f1": 0.1285714285714286,
        "unresolved_rate": 0.0
      },
      "prompted_llm": {
        "accuracy": 0.2857142857142857,
        "macro_f1": 0.16666666666666666,
        "unresolved_rate": 0.0
      }
    },
    "institution": {
      "mock": {
        "accuracy": 0.7142857142857143,
        "macro_f1": 0.738095238095238,
        "unresolved_rate": 0.23809523809523808
      },
      "chronological": {
        "accuracy": 0.2857142857142857,
        "macro_f1": 0.1314935064935065,
        "unresolved_rate": 0.0
      },
      "page_change": {
        "accuracy": 0.14285714285714285,
        "macro_f1": 0.03571428571428571,
        "unresolved_rate": 0.0
      },
      "nli": {
        "accuracy": 0.47619047619047616,
        "macro_f1": 0.38021978021978026,
        "unresolved_rate": 0.0
      },
      "prompted_llm": {
        "accuracy": 0.5714285714285714,
        "macro_f1": 0.5238095238095237,
        "unresolved_rate": 0.0
      }
    }
  }
}
```

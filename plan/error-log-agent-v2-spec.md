# Error Log Agent v2 기획서

> **목적**: K3s 클러스터에 배포된 데이터 파이프라인 서비스와 Qwen VLM API의 에러 로그를 수집/분석하고, Slack을 통해 사용자 승인 기반으로 코드를 자동 수정한 뒤 K3s에 재배포하는 LangGraph 에이전트
>
> **대상 독자**: Claude Code에게 전달하여 구현을 지시하기 위한 상세 기획서
>
> **이전 버전**: error-log-agent v1 (로컬 FastAPI 서비스 대상, 로컬 파일 로그 수집 방식)

---

## 1. 프로젝트 개요

### 1.1 v1 대비 변경 사항

| 항목 | v1 | v2 |
|------|----|----|
| 모니터링 대상 | 로컬 target-service (테스트용) | K3s 데이터 파이프라인 서비스 + Qwen API |
| 로그 수집 방식 | 로컬 파일 읽기 (file offset) | kubectl logs (K3s Pod) + 로컬 파일 (Mac Studio) |
| 코드 수정 후 | Git 브랜치 커밋만 | Git 커밋 → Harbor 이미지 빌드 → K3s 스테이징 배포 → 검증 후 프로덕션 배포 |
| 에이전트 실행 환경 | 로컬 터미널 (uvicorn) | K3s Pod (컨테이너화) |
| UI | 없음 (터미널 + Slack) | 웹 대시보드 + Slack |
| LLM | GPT-4o-mini | GPT-4o-mini (분석) + Qwen 3 VL 32B (보조, 선택적) |

### 1.2 핵심 워크플로우

```
[K3s Pod 로그 / Mac Studio 로그] → [주기적 수집 (2분)] → [에러/Traceback 파싱]
       |
[LangGraph Agent: 에러 분석 + 코드 분석 + 웹 검색]
       |
[Slack Bot: 에러 원인 예상 + 수정 계획 전송]
       |
[사용자 피드백: 승인 / 거절 / 기타 의견]
       |
  +--------+------------+
  승인      거절        기타 의견
  |        |           |
[Git 커밋   [종료/로그]  [피드백 반영 →
 → 이미지                에이전트 재분석]
 빌드/Push
 → 스테이징
 배포]
  |
[스테이징 검증 → 통과 시 프로덕션 배포]
  |
[Slack 수정 완료 보고 + 웹 대시보드 업데이트]
```

### 1.3 기술 스택 요약

| 항목 | 선택 | 비고 |
|------|------|------|
| 에이전트 프레임워크 | LangGraph 1.0+ / LangChain 1.0+ | 상태 머신 기반 에이전트 |
| LLM (메인) | OpenAI GPT-4o-mini | 코드 분석, 수정 계획 생성 |
| LLM (보조) | Qwen 3 VL 32B | 로컬 모델, 이미지 포함 에러 분석 (선택적) |
| 로그 수집 | kubectl logs + 파일 로그 | K3s Pod 로그 + Mac Studio 파일 로그 |
| 모니터링 대상 | 데이터 파이프라인 서비스 (FastAPI) | K3s apps 네임스페이스 배포 |
| Slack 연동 | Slack Bot (Socket Mode) | Interactive Messages API |
| 코드 수정 | Git + Harbor + kubectl | 브랜치 → 이미지 빌드 → K3s 배포 |
| 웹 검색 | Tavily Search API | 에러 해결책 검색 |
| 웹 대시보드 | FastAPI + React (또는 Next.js) | 에러 통계, 수정 이력, 서비스 관리 |
| 컨테이너 레지스트리 | Harbor (192.168.50.10:8880) | 사내 이미지 레지스트리 |
| 오케스트레이션 | K3s (k3s v1.34.5+k3s1) | 4노드 클러스터 |
| DB | PostgreSQL (K3s data 네임스페이스) | 기존 인프라 활용 |
| 오브젝트 스토리지 | MinIO (K3s data 네임스페이스) | 파일 저장 |
| 검색 엔진 | OpenSearch (K3s data 네임스페이스) | 로그 인덱싱 (선택적) |
| 수집 주기 | 설정 가능 (기본 2분) | config.yaml로 관리 |

---

## 2. 인프라 현황

### 2.1 K3s 클러스터

| 노드 | Hostname | IP | 역할 |
|------|----------|----|----|
| Server 0 | atdev-server-00 | 192.168.50.10 | Control Plane + etcd + Harbor |
| Worker 1 | atdev-server-01 | 192.168.50.11 | Worker (데이터 노드, 48GB RAM) |
| Server 2 | atdev-server-02 | 192.168.50.12 | Control Plane + etcd |
| Server 3 | atdev-server-03 | 192.168.50.13 | Control Plane + etcd |

### 2.2 기존 서비스 (활용 가능)

| 서비스 | 네임스페이스 | K8s 내부 주소 | 용도 |
|--------|------------|-------------|------|
| PostgreSQL | data | postgres.data.svc:5432 | 파이프라인 결과 저장, 에이전트 상태 저장 |
| MinIO | data | minio.data.svc:9000 | 업로드 파일 저장 |
| OpenSearch | data | opensearch.data.svc:9200 | 에러 로그 인덱싱 (선택적) |
| Prometheus | monitoring | prometheus.monitoring.svc | 메트릭 수집 |
| Grafana | monitoring | grafana.monitoring.svc | 대시보드 |

### 2.3 Qwen API (K3s 외부)

| 항목 | 값 |
|------|---|
| 위치 | Mac Studio (192.168.50.26) |
| 모델 | Qwen3-VL 32B (MLX, 4bit) |
| Base URL | http://192.168.50.26:32000/v1 (내부) / https://qwen.atdev.ai (외부) |
| API Key | MOAI-MAC-SECRET-KEY-2025 |
| 로그 경로 | /Users/sam/dev/Qwen3VL-32b/logs/mlx_server.stderr.log |
| 관리 | launchd (com.qwen3vl.mlx) |

### 2.4 Harbor (컨테이너 레지스트리)

| 항목 | 값 |
|------|---|
| URL (내부) | http://192.168.50.10:8880 |
| URL (외부) | https://harbor.atdev.ai |
| 인증 | admin / Atdev25@! |

### 2.5 Cloudflare Tunnel

| Tunnel | 용도 |
|--------|------|
| k8s-cluster | K8s 서비스 전체 + Harbor |
| mac-studio | Qwen API (Mac Studio) |

---

## 3. 프로젝트 구성 (2개 프로젝트)

### 3.1 전체 구조

```
workspace/
+-- data-pipeline-service/    # 프로젝트 1: 모니터링 대상 (K3s 배포)
|   +-- src/
|   +-- Dockerfile
|   +-- k8s/
|   +-- pyproject.toml
|   +-- ...
|
+-- error-log-agent-v2/       # 프로젝트 2: 에이전트 (K3s 배포)
    +-- src/
    +-- frontend/             # 웹 대시보드
    +-- Dockerfile
    +-- k8s/
    +-- pyproject.toml
    +-- ...
```

---

## 4. 프로젝트 1: 데이터 파이프라인 서비스

### 4.1 개요

사용자가 파일(CSV, 이미지, 텍스트 등)을 업로드하면, 파이프라인이 전처리 → Qwen 분석 → 결과 저장까지 수행하는 FastAPI 서비스. Airflow 도입 전까지 경량 파이프라인 역할을 한다.

### 4.2 핵심 기능

| 기능 | 설명 |
|------|------|
| 파일 업로드 | CSV, 이미지, 텍스트 파일 업로드 (API + 웹) |
| MinIO 저장 | 업로드 파일을 MinIO 버킷에 저장 |
| 전처리 | 파일 포맷 검증, 데이터 정제, 이미지 리사이징 등 |
| Qwen 분석 | 텍스트 요약/분류, 이미지 분석 (VLM), 데이터 추출 |
| 결과 저장 | 분석 결과를 PostgreSQL에 저장 |
| 파이프라인 상태 관리 | 각 단계의 상태 추적 (pending → processing → completed / failed) |
| 파이프라인 재실행 | 실패한 파이프라인을 재실행 |

### 4.3 디렉토리 구조

```
data-pipeline-service/
+-- pyproject.toml
+-- Dockerfile
+-- config.yaml
+-- .env
+-- .gitignore
|
+-- k8s/                          # K8s 매니페스트
|   +-- namespace.yaml
|   +-- deployment.yaml
|   +-- service.yaml
|   +-- configmap.yaml
|   +-- secret.yaml
|
+-- src/
|   +-- __init__.py
|   |
|   +-- main.py                   # FastAPI 앱 엔트리포인트
|   +-- config.py                 # 설정 관리 (Pydantic Settings)
|   |
|   +-- api/
|   |   +-- __init__.py
|   |   +-- routes.py             # API 엔드포인트
|   |   +-- deps.py               # 의존성 주입
|   |
|   +-- pipeline/
|   |   +-- __init__.py
|   |   +-- manager.py            # 파이프라인 매니저 (상태 관리)
|   |   +-- stages/
|   |   |   +-- __init__.py
|   |   |   +-- upload.py         # 1단계: 파일 업로드 → MinIO
|   |   |   +-- preprocess.py     # 2단계: 전처리 (포맷 검증, 정제)
|   |   |   +-- analyze.py        # 3단계: Qwen API 호출 (분석)
|   |   |   +-- store.py          # 4단계: 결과 저장 (PostgreSQL)
|   |   +-- errors.py             # 파이프라인 커스텀 예외
|   |
|   +-- services/
|   |   +-- __init__.py
|   |   +-- minio_client.py       # MinIO 연동
|   |   +-- qwen_client.py        # Qwen API 클라이언트
|   |   +-- db_client.py          # PostgreSQL 연동
|   |
|   +-- models/
|   |   +-- __init__.py
|   |   +-- pipeline.py           # Pipeline, PipelineStage 모델
|   |   +-- file.py               # UploadedFile 모델
|   |   +-- result.py             # AnalysisResult 모델
|   |
|   +-- utils/
|       +-- __init__.py
|       +-- logging_config.py     # structlog 설정
|
+-- tests/
    +-- __init__.py
    +-- test_pipeline.py
    +-- test_qwen_client.py
```

### 4.4 Config 설정 (`config.yaml`)

```yaml
service:
  name: "data-pipeline-service"
  version: "1.0.0"

server:
  host: "0.0.0.0"
  port: 8000

minio:
  endpoint: "minio.data.svc:9000"
  access_key: "${MINIO_ACCESS_KEY}"
  secret_key: "${MINIO_SECRET_KEY}"
  bucket: "pipeline-data"
  secure: false

postgresql:
  host: "postgres.data.svc"
  port: 5432
  database: "pipeline"
  user: "${PG_USER}"
  password: "${PG_PASSWORD}"

qwen:
  base_url: "http://192.168.50.26:32000/v1"
  api_key: "${QWEN_API_KEY}"
  model: "qwen3-vl:32b"
  max_tokens: 2048
  timeout: 120  # Qwen은 순차 처리라 타임아웃 넉넉하게

pipeline:
  max_file_size_mb: 50
  supported_formats:
    - "csv"
    - "json"
    - "txt"
    - "jpg"
    - "jpeg"
    - "png"
  max_concurrent_pipelines: 3
  retry_max_attempts: 3
  retry_delay_seconds: 10

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

### 4.5 환경변수 (`.env`)

```bash
# MinIO
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=Atdev25@!

# PostgreSQL
PG_USER=admin
PG_PASSWORD=Atdev25@!

# Qwen API
QWEN_API_KEY=MOAI-MAC-SECRET-KEY-2025
```

### 4.6 API 엔드포인트

```
GET  /health                           # 헬스체크
GET  /docs                             # Swagger UI

POST /api/v1/pipelines                 # 파이프라인 생성 (파일 업로드)
GET  /api/v1/pipelines                 # 파이프라인 목록 조회
GET  /api/v1/pipelines/{pipeline_id}   # 파이프라인 상태 조회
POST /api/v1/pipelines/{pipeline_id}/retry  # 실패한 파이프라인 재실행
DELETE /api/v1/pipelines/{pipeline_id} # 파이프라인 삭제

GET  /api/v1/results                   # 분석 결과 목록
GET  /api/v1/results/{result_id}       # 분석 결과 상세
```

### 4.7 파이프라인 상태 모델

```python
# src/models/pipeline.py
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

class PipelineStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PREPROCESSING = "preprocessing"
    ANALYZING = "analyzing"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"

class Pipeline(BaseModel):
    id: str                          # UUID
    filename: str                    # 원본 파일명
    file_type: str                   # csv, json, jpg, ...
    file_size: int                   # bytes
    minio_path: str                  # MinIO 저장 경로
    status: PipelineStatus
    current_stage: str               # 현재 진행 중인 단계
    error_message: str | None        # 실패 시 에러 메시지
    error_traceback: str | None      # 실패 시 traceback
    retry_count: int                 # 재시도 횟수
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
```

### 4.8 파이프라인 단계별 상세

**Stage 1: Upload (파일 업로드)**
```python
# src/pipeline/stages/upload.py
async def upload_stage(file: UploadFile, pipeline: Pipeline) -> Pipeline:
    """파일을 MinIO에 업로드"""
    # 1. 파일 크기 검증 (max_file_size_mb 초과 시 에러)
    # 2. 파일 포맷 검증 (supported_formats에 포함되지 않으면 에러)
    # 3. MinIO에 업로드 (pipeline-data 버킷)
    # 4. Pipeline 상태 업데이트
```

**Stage 2: Preprocess (전처리)**
```python
# src/pipeline/stages/preprocess.py
async def preprocess_stage(pipeline: Pipeline) -> Pipeline:
    """파일 전처리"""
    # CSV: 인코딩 감지, 헤더 검증, 빈 행 제거
    # JSON: 스키마 검증, 중첩 구조 평탄화
    # 이미지: 리사이징 (Qwen 입력 최적화), 포맷 변환
    # 텍스트: 인코딩 변환, 빈 줄 정리
```

**Stage 3: Analyze (Qwen 분석)**
```python
# src/pipeline/stages/analyze.py
async def analyze_stage(pipeline: Pipeline) -> Pipeline:
    """Qwen API를 호출하여 데이터 분석"""
    # CSV/JSON: 데이터 요약, 이상치 탐지, 컬럼 설명 생성
    # 이미지: 이미지 내용 설명, 텍스트 추출 (OCR), 분류
    # 텍스트: 요약, 키워드 추출, 감성 분석
```

**Stage 4: Store (결과 저장)**
```python
# src/pipeline/stages/store.py
async def store_stage(pipeline: Pipeline, result: AnalysisResult) -> Pipeline:
    """분석 결과를 PostgreSQL에 저장"""
    # 1. analysis_results 테이블에 결과 저장
    # 2. Pipeline 상태를 COMPLETED로 업데이트
    # 3. 원본 파일 메타데이터 업데이트
```

### 4.9 에러 발생 가능 지점

인위적 에러 주입 없이, 정상 운영 중 자연스럽게 발생할 수 있는 에러들:

| 단계 | 에러 유형 | 발생 조건 |
|------|-----------|----------|
| Upload | MinIO ConnectionError | MinIO 서비스 일시 장애 |
| Upload | FileTooLargeError | 업로드 파일 크기 초과 |
| Upload | UnsupportedFormatError | 지원하지 않는 파일 포맷 |
| Preprocess | UnicodeDecodeError | CSV 인코딩 문제 |
| Preprocess | JSONDecodeError | 잘못된 JSON 형식 |
| Preprocess | PIL.UnidentifiedImageError | 손상된 이미지 파일 |
| Analyze | httpx.TimeoutException | Qwen API 타임아웃 (순차 처리 특성) |
| Analyze | httpx.ConnectError | Qwen API 서버 연결 실패 |
| Analyze | KeyError / JSONDecodeError | Qwen 응답 파싱 실패 |
| Analyze | RateLimitError | Qwen 동시 요청 한계 초과 |
| Store | psycopg2.OperationalError | PostgreSQL 연결 실패 |
| Store | psycopg2.IntegrityError | 중복 데이터 저장 시도 |

### 4.10 DB 스키마 (PostgreSQL)

```sql
-- pipeline DB 생성 (기존 PostgreSQL 인스턴스에 새 DB)
CREATE DATABASE pipeline;

-- 파이프라인 테이블
CREATE TABLE pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_size BIGINT NOT NULL,
    minio_path VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_stage VARCHAR(50),
    error_message TEXT,
    error_traceback TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 분석 결과 테이블
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID REFERENCES pipelines(id) ON DELETE CASCADE,
    result_type VARCHAR(50) NOT NULL,  -- summary, classification, extraction, ...
    result_data JSONB NOT NULL,         -- 분석 결과 (구조화된 JSON)
    model_used VARCHAR(100),            -- 사용된 모델 (qwen3-vl:32b 등)
    tokens_used INT,
    processing_time_ms INT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_pipelines_status ON pipelines(status);
CREATE INDEX idx_pipelines_created ON pipelines(created_at DESC);
CREATE INDEX idx_results_pipeline ON analysis_results(pipeline_id);
```

### 4.11 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY config.yaml .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4.12 K8s 매니페스트

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: pipeline
  labels:
    tier: pipeline
```

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: data-pipeline
  namespace: pipeline
spec:
  replicas: 1
  selector:
    matchLabels:
      app: data-pipeline
  template:
    metadata:
      labels:
        app: data-pipeline
    spec:
      containers:
      - name: data-pipeline
        image: harbor:8880/custom/data-pipeline:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: pipeline-secrets
        - configMapRef:
            name: pipeline-config
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
```

```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: data-pipeline
  namespace: pipeline
spec:
  selector:
    app: data-pipeline
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP
```

### 4.13 로깅 규약

에이전트가 로그를 파싱할 수 있도록 표준 로그 포맷을 사용한다.

```
# 표준 로그 형식
{timestamp} - {logger_name} - {level} - {message}

# 예시: 정상 로그
2026-03-23 14:30:15 - data-pipeline - INFO - Pipeline abc123 started: uploading file.csv

# 예시: 에러 (traceback 포함)
2026-03-23 14:30:45 - data-pipeline - ERROR - Pipeline abc123 failed at analyze stage
Traceback (most recent call last):
  File "/app/src/pipeline/stages/analyze.py", line 42, in analyze_stage
    response = await qwen_client.chat(messages)
  File "/app/src/services/qwen_client.py", line 28, in chat
    return await self.client.post(url, json=payload)
httpx.ConnectError: All connection attempts failed
```

---

## 5. 프로젝트 2: Error Log Agent v2

### 5.1 개요

K3s Pod 로그와 Mac Studio 파일 로그를 수집하여 에러를 분석하고, 코드 수정 → 이미지 빌드 → K3s 배포까지 자동화하는 에이전트. 웹 대시보드를 통해 에러 통계 및 수정 이력을 시각화한다.

### 5.2 디렉토리 구조

```
error-log-agent-v2/
+-- pyproject.toml
+-- Dockerfile
+-- config.yaml
+-- .env
+-- .gitignore
|
+-- k8s/                              # K8s 매니페스트
|   +-- deployment.yaml
|   +-- service.yaml
|   +-- configmap.yaml
|   +-- secret.yaml
|   +-- rbac.yaml                     # kubectl logs 권한
|
+-- src/
|   +-- __init__.py
|   |
|   +-- server/                       # FastAPI 서버
|   |   +-- __init__.py
|   |   +-- app.py                    # FastAPI 앱 + lifespan
|   |   +-- routes.py                 # REST API 엔드포인트
|   |   +-- scheduler.py             # APScheduler 설정
|   |
|   +-- agent/                        # LangGraph 에이전트
|   |   +-- __init__.py
|   |   +-- graph.py                  # LangGraph 그래프 정의
|   |   +-- state.py                  # AgentState 정의
|   |   +-- nodes/
|   |   |   +-- __init__.py
|   |   |   +-- log_collector.py      # 로그 수집 (kubectl logs + 파일)
|   |   |   +-- code_analyzer.py      # 코드 분석
|   |   |   +-- fix_planner.py        # 수정 계획
|   |   |   +-- human_approval.py     # 사용자 승인 (Slack)
|   |   |   +-- code_fixer.py         # 코드 수정
|   |   |   +-- image_builder.py      # Docker 이미지 빌드 + Harbor push
|   |   |   +-- k8s_deployer.py       # K8s 스테이징/프로덕션 배포
|   |   |   +-- monitor.py            # 수정 후 모니터링
|   |   +-- edges.py                  # 조건부 엣지 로직
|   |
|   +-- log_collector/                # 로그 수집 엔진
|   |   +-- __init__.py
|   |   +-- k8s_collector.py          # kubectl logs 기반 수집
|   |   +-- file_collector.py         # 파일 기반 수집 (Mac Studio 등)
|   |   +-- parser.py                 # Python traceback 파서
|   |   +-- filter.py                 # ERROR 레벨 필터링 + 중복 제거
|   |
|   +-- tools/                        # LangChain Tools
|   |   +-- __init__.py
|   |   +-- file_system.py            # 파일 읽기/쓰기
|   |   +-- git_ops.py                # Git 브랜치/커밋/머지
|   |   +-- web_search.py             # Tavily 검색
|   |   +-- slack_messenger.py        # Slack 메시지 전송
|   |   +-- k8s_ops.py                # kubectl 명령 실행
|   |   +-- harbor_ops.py             # Harbor 이미지 빌드/push
|   |
|   +-- slack/                        # Slack Bot
|   |   +-- __init__.py
|   |   +-- bot.py                    # Slack Bolt 앱
|   |   +-- handlers.py              # Interactive Message + @mention 핸들러
|   |   +-- message_builder.py        # Block Kit 메시지 빌더
|   |
|   +-- deployer/                     # K8s 배포 관리
|   |   +-- __init__.py
|   |   +-- staging.py                # 스테이징 배포 + 검증
|   |   +-- production.py             # 프로덕션 배포
|   |   +-- rollback.py               # 롤백
|   |
|   +-- db/                           # 데이터베이스 관리
|   |   +-- __init__.py
|   |   +-- manager.py                # DB 매니저 (PostgreSQL)
|   |   +-- error_statistics.py       # 에러 통계
|   |
|   +-- models/                       # 데이터 모델
|   |   +-- __init__.py
|   |   +-- log_entry.py
|   |   +-- analysis_result.py
|   |   +-- fix_plan.py
|   |   +-- deployment.py
|   |
|   +-- config/
|   |   +-- __init__.py
|   |   +-- settings.py               # Pydantic Settings
|   |   +-- logging_config.py
|   |
|   +-- utils/
|       +-- __init__.py
|       +-- cost_tracker.py
|       +-- error_handler.py
|
+-- frontend/                         # 웹 대시보드
|   +-- package.json
|   +-- src/
|   |   +-- App.jsx
|   |   +-- pages/
|   |   |   +-- Dashboard.jsx         # 메인 대시보드
|   |   |   +-- Errors.jsx            # 에러 목록/상세
|   |   |   +-- History.jsx           # 수정 이력
|   |   |   +-- Services.jsx          # 모니터링 대상 서비스 관리
|   |   |   +-- Settings.jsx          # 설정
|   |   +-- components/
|   |       +-- ErrorChart.jsx         # 에러 통계 차트
|   |       +-- PipelineStatus.jsx     # 파이프라인 상태
|   |       +-- DeploymentLog.jsx      # 배포 로그
|   +-- Dockerfile
|
+-- tests/
    +-- __init__.py
    +-- test_k8s_collector.py
    +-- test_agent_graph.py
    +-- test_deployer.py
```

### 5.3 Agent State 정의

```python
# src/agent/state.py
from typing import TypedDict, Literal, Annotated, Optional
from langgraph.graph.message import add_messages

class ErrorInfo(TypedDict):
    timestamp: str
    level: str                       # ERROR, CRITICAL
    message: str
    traceback: str | None
    file_path: str | None
    line_number: int | None
    function_name: str | None
    source: str                      # "k8s_pod" | "file_log"
    pod_name: str | None             # K8s Pod 이름
    namespace: str | None            # K8s 네임스페이스
    container: str | None            # 컨테이너 이름

class DeploymentInfo(TypedDict):
    staging_namespace: str
    staging_deployment: str
    production_namespace: str
    production_deployment: str
    image_tag: str
    harbor_image: str                # harbor:8880/custom/xxx:tag

class AgentState(TypedDict):
    thread_id: str
    error_logs: list[ErrorInfo]
    source_code_context: dict[str, str]
    analysis: str
    fix_plan: dict | None
    human_feedback: dict | None
    git_branch: str | None
    git_commit_hash: str | None
    deployment: DeploymentInfo | None
    staging_result: str | None       # "healthy" | "unhealthy" | "timeout"
    post_fix_status: str | None
    iteration_count: int
    max_iterations: int
    messages: Annotated[list, add_messages]
```

### 5.4 LangGraph 그래프 (v2)

```
                    +-------------+
                    |   START     |
                    +------+------+
                           |
                    +------v------+
                    | collect_logs|  ← kubectl logs + 파일 로그
                    +------+------+
                           |
                    +------v------+     no_errors
                    | has_errors? |-----------> END
                    +------+------+
                           | has_errors
                    +------v------+
              +---->|analyze_code |<-----------+
              |     +------+------+            |
              |            |                   |
              |     +------v------+            |
              |     |  plan_fix   |            |
              |     +------+------+            |
              |            |                   |
              |     +------v----------+        |
              |     |request_approval |        |
              |     |  (Slack 전송)   |        |
              |     +------+----------+        |
              |            |                   |
              |     +------v------+  feedback  |
              |     |  route?     |------------+
              |     +--+-----+---+
              |        |     |
              |  approve|    |reject
              |        |     |
              |  +-----v--+  +---> END
              |  |apply_fix|
              |  +----+---+
              |       |
              |  +----v--------+
              |  |build_image  |  ← Docker 빌드 + Harbor push
              |  +----+--------+
              |       |
              |  +----v-----------+
              |  |deploy_staging  |  ← K8s 스테이징 배포
              |  +----+-----------+
              |       |
              |  +----v-----------+
              |  |verify_staging  |  ← 헬스체크 + 에러 확인
              |  +----+-----------+
              |       |
              |  +----v--------+  unhealthy
              |  |staging_ok?  |-----------> rollback → report → END
              |  +----+--------+
              |       | healthy
              |  +----v-----------+
              |  |deploy_production|
              |  +----+-----------+
              |       |
              |  +----v----+
              |  | monitor  |
              |  +----+----+
              |       |
              |  +----v----+  recurring
              |  | result?  |-----------> (back to analyze_code)
              |  +----+----+
              |       | resolved
              |  +----v----+
              |  | report   |
              |  +----+----+
              |       |
              |       v
              |      END
```

### 5.5 v2 신규 노드 상세

#### `build_image` -- 이미지 빌드 노드

```python
# src/agent/nodes/image_builder.py
async def build_image_node(state: AgentState) -> AgentState:
    """수정된 코드로 Docker 이미지를 빌드하고 Harbor에 push"""
    # 1. 수정된 코드가 있는 브랜치에서 Docker build
    # 2. 이미지 태그: harbor:8880/custom/{service}:{commit_hash[:8]}
    # 3. Harbor에 push
    # 4. state에 이미지 정보 저장
```

#### `deploy_staging` -- 스테이징 배포 노드

```python
# src/agent/nodes/k8s_deployer.py
async def deploy_staging_node(state: AgentState) -> AgentState:
    """스테이징 네임스페이스에 수정된 이미지를 배포"""
    # 1. pipeline-staging 네임스페이스에 배포 (없으면 생성)
    # 2. 기존 프로덕션과 동일한 스펙 + 새 이미지
    # 3. Pod Ready 대기 (타임아웃 120초)
```

#### `verify_staging` -- 스테이징 검증 노드

```python
# src/deployer/staging.py
async def verify_staging(deployment: DeploymentInfo) -> str:
    """스테이징 배포의 정상 동작 확인"""
    # 1. 헬스체크 엔드포인트 호출
    # 2. 60초간 에러 로그 모니터링
    # 3. 동일 에러 재발 여부 확인
    # 결과: "healthy" | "unhealthy" | "timeout"
```

#### `deploy_production` -- 프로덕션 배포 노드

```python
# src/deployer/production.py
async def deploy_production(deployment: DeploymentInfo) -> dict:
    """프로덕션 네임스페이스에 배포"""
    # 1. 기존 이미지 태그 백업 (롤백용)
    # 2. kubectl set image로 프로덕션 이미지 교체
    # 3. rollout status 확인
    # 4. Slack으로 배포 완료 보고
```

### 5.6 로그 수집 방식

#### K8s Pod 로그 수집

```python
# src/log_collector/k8s_collector.py
import subprocess

class K8sLogCollector:
    """kubectl logs로 K8s Pod 로그를 수집"""

    async def collect(self, namespace: str, label_selector: str,
                      since_seconds: int = 120) -> list[str]:
        """지정된 Pod의 최근 로그 수집"""
        cmd = [
            "kubectl", "logs",
            "-n", namespace,
            "-l", label_selector,
            f"--since={since_seconds}s",
            "--tail=500"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.splitlines()
```

#### Mac Studio 파일 로그 수집 (SSH 또는 에이전트)

```python
# src/log_collector/file_collector.py
class RemoteFileCollector:
    """원격 서버의 파일 로그 수집 (SSH)"""

    async def collect(self, host: str, log_path: str,
                      last_offset: int = 0) -> tuple[list[str], int]:
        """SSH로 원격 서버의 로그 파일 읽기"""
        # ssh sam@192.168.50.26 "tail -c +{offset} {log_path}"
        # 또는 K8s 내부에서 접근 가능하면 HTTP로 수집
```

### 5.7 RBAC (K8s 권한)

에이전트가 K8s 리소스에 접근하려면 ServiceAccount + RBAC가 필요하다.

```yaml
# k8s/rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: error-log-agent
  namespace: pipeline

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: error-log-agent-role
rules:
  # 로그 읽기
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list"]
  # 배포 관리
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "update", "patch"]
  # 네임스페이스 관리 (스테이징)
  - apiGroups: [""]
    resources: ["namespaces", "services"]
    verbs: ["get", "list", "create"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: error-log-agent-binding
subjects:
  - kind: ServiceAccount
    name: error-log-agent
    namespace: pipeline
roleRef:
  kind: ClusterRole
  name: error-log-agent-role
  apiGroup: rbac.authorization.k8s.io
```

### 5.8 Config 설정 (`config.yaml`)

```yaml
agent:
  name: "error-log-agent-v2"
  version: "2.0.0"

log_collector:
  interval_seconds: 120
  sources:
    # K8s Pod 로그
    - type: "k8s_pod"
      namespace: "pipeline"
      label_selector: "app=data-pipeline"
      since_seconds: 120
    # Mac Studio Qwen 로그 (SSH)
    - type: "remote_file"
      host: "192.168.50.26"
      user: "sam"
      log_path: "/Users/sam/dev/Qwen3VL-32b/logs/mlx_server.stderr.log"
  log_levels:
    - "ERROR"
    - "CRITICAL"

target_projects:
  - name: "data-pipeline-service"
    git_repo: "git@github.com:xxx/data-pipeline-service.git"  # 또는 로컬 경로
    root_path: "/workspace/data-pipeline-service"
    k8s:
      namespace: "pipeline"
      deployment: "data-pipeline"
      staging_namespace: "pipeline-staging"
    harbor:
      project: "custom"
      image_name: "data-pipeline"
    exclude_paths:
      - "venv/"
      - "__pycache__/"
      - ".git/"
      - "k8s/"

llm:
  provider: "openai"
  model: "gpt-4o-mini"
  max_tokens: 4096
  temperature: 0.0

web_search:
  enabled: true
  provider: "tavily"
  max_results: 5

slack:
  enabled: true
  channel: "#error-log-agent"
  approval_timeout_seconds: 3600

deployer:
  staging_verify_seconds: 60
  staging_timeout_seconds: 120
  production_rollout_timeout: 300
  auto_rollback: true

database:
  host: "postgres.data.svc"
  port: 5432
  database: "error_log_agent"
  user: "${PG_USER}"
  password: "${PG_PASSWORD}"

dashboard:
  enabled: true
  port: 3000
```

### 5.9 웹 대시보드

#### 페이지 구성

| 페이지 | 경로 | 기능 |
|--------|------|------|
| 대시보드 | / | 에러 발생 추이 차트, 최근 에러 목록, 서비스 상태 |
| 에러 상세 | /errors | 에러 목록, 필터링, 상세 보기 (traceback, 분석 결과) |
| 수정 이력 | /history | 코드 수정 이력, diff, 배포 상태 |
| 서비스 관리 | /services | 모니터링 대상 서비스 추가/제거/설정 |
| 설정 | /settings | 수집 주기, LLM 설정, Slack 설정 |

#### 대시보드 API

```
GET  /api/dashboard/summary          # 대시보드 요약 데이터
GET  /api/dashboard/errors           # 에러 목록 (페이징, 필터)
GET  /api/dashboard/errors/{id}      # 에러 상세
GET  /api/dashboard/stats/timeline   # 시간별 에러 추이
GET  /api/dashboard/stats/by-type    # 타입별 에러 통계
GET  /api/dashboard/history          # 수정 이력
GET  /api/dashboard/services         # 모니터링 대상 서비스 목록
POST /api/dashboard/services         # 서비스 추가
PUT  /api/dashboard/services/{id}    # 서비스 설정 변경
DELETE /api/dashboard/services/{id}  # 서비스 제거
```

### 5.10 DB 스키마 (에이전트용, PostgreSQL)

```sql
CREATE DATABASE error_log_agent;

-- 에러 로그
CREATE TABLE error_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMP NOT NULL,
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    traceback TEXT,
    file_path VARCHAR(500),
    line_number INT,
    function_name VARCHAR(200),
    error_type VARCHAR(200),
    source VARCHAR(20) NOT NULL,       -- k8s_pod, file_log
    pod_name VARCHAR(200),
    namespace VARCHAR(100),
    service_name VARCHAR(200),
    signature VARCHAR(64),             -- MD5 (중복 제거용)
    created_at TIMESTAMP DEFAULT NOW()
);

-- 에러 통계
CREATE TABLE error_statistics (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    hour INT NOT NULL,
    error_type VARCHAR(200),
    error_level VARCHAR(20),
    service_name VARCHAR(200),
    count INT DEFAULT 1,
    UNIQUE(date, hour, error_type, error_level, service_name)
);

-- 수정 이력
CREATE TABLE fix_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    error_log_id UUID REFERENCES error_logs(id),
    thread_id VARCHAR(200),
    analysis TEXT,
    fix_plan JSONB,
    action VARCHAR(20),                -- approve, reject, feedback
    git_branch VARCHAR(200),
    git_commit VARCHAR(64),
    harbor_image VARCHAR(500),
    staging_result VARCHAR(20),
    production_deployed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- 모니터링 대상 서비스
CREATE TABLE monitored_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    source_type VARCHAR(20) NOT NULL,  -- k8s_pod, file_log
    namespace VARCHAR(100),
    label_selector VARCHAR(200),
    log_path VARCHAR(500),
    git_repo VARCHAR(500),
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_error_logs_timestamp ON error_logs(timestamp DESC);
CREATE INDEX idx_error_logs_service ON error_logs(service_name);
CREATE INDEX idx_error_logs_signature ON error_logs(signature);
CREATE INDEX idx_fix_history_created ON fix_history(created_at DESC);
CREATE INDEX idx_error_stats_date ON error_statistics(date, hour);
```

---

## 6. 배포 파이프라인 (에이전트가 수행)

### 6.1 전체 배포 흐름

```
코드 수정 (Git 커밋)
    |
    v
Docker 이미지 빌드
    |
    v
Harbor에 Push (harbor:8880/custom/data-pipeline:{commit_hash})
    |
    v
스테이징 배포 (pipeline-staging 네임스페이스)
    |
    v
스테이징 검증 (헬스체크 + 60초 에러 모니터링)
    |
    +--- 실패 → 롤백 + Slack 보고 → END
    |
    v (성공)
프로덕션 배포 (pipeline 네임스페이스, 이미지 교체)
    |
    v
프로덕션 검증 (rollout status)
    |
    +--- 실패 → 롤백 + Slack 보고 → END
    |
    v (성공)
Slack 배포 완료 보고 + 대시보드 업데이트
```

### 6.2 이미지 빌드 방식

에이전트가 K8s Pod 내부에서 실행되므로, 이미지 빌드는 다음 방식 중 하나를 선택:

**방식 1: 원격 빌드 (SSH)**
- 에이전트가 Server 0 (Harbor가 있는 노드)에 SSH로 접속
- git clone → docker build → docker push

**방식 2: Kaniko (K8s 내부 빌드)**
- Kaniko Pod을 생성하여 K8s 내부에서 이미지 빌드
- Harbor에 직접 push
- Docker daemon 불필요

**권장: 방식 1 (초기 단계에서 단순함)**

---

## 7. 환경변수 (`.env`)

```bash
# LLM
OPENAI_API_KEY=sk-proj-xxx

# Slack
SLACK_APP_TOKEN=xapp-xxx
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_SIGNING_SECRET=xxx

# Web Search
TAVILY_API_KEY=tvly-xxx

# PostgreSQL (K3s 내부)
PG_USER=admin
PG_PASSWORD=Atdev25@!

# Harbor
HARBOR_URL=http://192.168.50.10:8880
HARBOR_USER=admin
HARBOR_PASSWORD=Atdev25@!

# Qwen API
QWEN_API_KEY=MOAI-MAC-SECRET-KEY-2025

# SSH (Mac Studio 로그 수집용)
MAC_STUDIO_HOST=192.168.50.26
MAC_STUDIO_USER=sam
```

---

## 8. Slack 메시지 (v2 확장)

### 8.1 에러 감지 보고 (기존과 동일 + 서비스 정보 추가)

```
[ALERT] Error Log Agent v2 -- 에러 감지

서비스: data-pipeline-service
네임스페이스: pipeline
Pod: data-pipeline-7b8c9d-xxxxx
감지 시각: 2026-03-23 14:30:45
에러 타입: httpx.ConnectError
발생 위치: src/services/qwen_client.py:28

(이하 기존과 동일: 예상 원인, 수정 계획, diff, 버튼)
```

### 8.2 배포 완료 보고 (v2 신규)

```
[DEPLOY] Error Log Agent v2 -- 배포 완료

서비스: data-pipeline-service
수정 에러: httpx.ConnectError (Qwen API 연결 실패)

Git: fix/agent-connect-error-20260323-143045 (a1b2c3d)
이미지: harbor:8880/custom/data-pipeline:a1b2c3d

스테이징 검증: 통과 (60초간 에러 없음)
프로덕션 배포: 완료

[롤백] [상세 보기]
```

---

## 9. 보안 및 안전장치

| 안전장치 | 설명 |
|----------|------|
| Git 브랜치 격리 | 모든 수정은 별도 브랜치에서 수행 |
| 스테이징 검증 | 프로덕션 배포 전 반드시 스테이징에서 검증 |
| 자동 롤백 | 스테이징/프로덕션 검증 실패 시 자동 롤백 |
| 파일 수정 제한 | 한 번에 최대 5개 파일, 100줄 변경 |
| 경로 제한 | k8s/, Dockerfile 등 인프라 파일 수정 불가 |
| 무한루프 방지 | max_iterations: 3 초과 시 강제 종료 |
| 승인 타임아웃 | 1시간 초과 시 자동 취소 |
| RBAC | 에이전트 ServiceAccount에 최소 권한만 부여 |

---

## 10. Claude Code 구현 지시사항

> 이 기획서를 Claude Code에게 전달할 때 다음 순서로 구현을 지시하세요:

### Phase 1: 데이터 파이프라인 서비스 기반 구조
1. 프로젝트 초기화 (pyproject.toml, 디렉토리 구조)
2. config.yaml + settings.py (Pydantic Settings)
3. 데이터 모델 정의 (Pipeline, AnalysisResult 등)
4. FastAPI 앱 + API 엔드포인트

### Phase 2: 파이프라인 구현
5. MinIO 클라이언트 구현 (파일 업로드/다운로드)
6. Qwen API 클라이언트 구현
7. PostgreSQL 클라이언트 구현
8. 파이프라인 매니저 + 4단계 구현 (upload → preprocess → analyze → store)
9. 에러 핸들링 + 재시도 로직

### Phase 3: 파이프라인 서비스 컨테이너화 + K8s 배포
10. Dockerfile 작성
11. K8s 매니페스트 작성 (deployment, service, configmap, secret)
12. Harbor에 이미지 push
13. K8s 배포 및 동작 확인

### Phase 4: Error Log Agent v2 기반 구조
14. 프로젝트 초기화
15. config.yaml + settings.py
16. 데이터 모델 정의
17. DB 스키마 생성 (PostgreSQL)

### Phase 5: 로그 수집
18. K8s Pod 로그 수집기 구현 (kubectl logs)
19. 원격 파일 로그 수집기 구현 (SSH)
20. Python traceback 파서 + 에러 필터
21. 에러 중복 제거 (MD5 signature)

### Phase 6: LangGraph 에이전트
22. AgentState 정의
23. 기존 노드 구현 (collect → analyze → plan → approval → fix)
24. 신규 노드 구현 (build_image → deploy_staging → verify → deploy_production)
25. 그래프 컴파일 + MemorySaver

### Phase 7: 배포 파이프라인
26. Docker 이미지 빌드 도구 구현
27. Harbor push 도구 구현
28. K8s 스테이징 배포 + 검증 구현
29. K8s 프로덕션 배포 + 롤백 구현

### Phase 8: Slack Bot
30. Slack Bolt 앱 (Socket Mode)
31. Interactive Message 핸들러 (승인/거절/피드백)
32. @mention 대화형 명령 (통계, 목록, 상태)
33. Block Kit 메시지 빌더

### Phase 9: 웹 대시보드
34. FastAPI 대시보드 API 구현
35. React 프론트엔드 구현
36. 에러 통계 차트, 수정 이력, 서비스 관리 페이지

### Phase 10: 에이전트 컨테이너화 + K8s 배포
37. Dockerfile 작성
38. K8s 매니페스트 (deployment, service, rbac)
39. Harbor에 이미지 push
40. K8s 배포 및 동작 확인

### Phase 11: 통합 테스트
41. 파이프라인 서비스에 파일 업로드 → 에러 발생
42. 에이전트가 로그 수집 → 분석 → Slack 전송
43. 승인 → 코드 수정 → 이미지 빌드 → 스테이징 배포 → 프로덕션 배포
44. 웹 대시보드에서 에러 통계 및 수정 이력 확인

---

## 11. 향후 확장 (Airflow 도입 후)

- Airflow DAG을 모니터링 대상에 추가
- DAG 코드 수정 → Airflow 재배포 자동화
- 파이프라인 서비스의 로직을 Airflow DAG으로 마이그레이션
- 멀티 서비스 동시 모니터링 확장

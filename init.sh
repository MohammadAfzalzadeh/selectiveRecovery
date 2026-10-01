kind create cluster --name takhfifan


helm repo add minio https://charts.min.io/
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install minio minio/minio -f minio-values.yaml -n minio --create-namespace


kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.22/releases/cnpg-1.22.1.yaml

kubectl create namespace database

kubectl apply -f pg-cluster.yaml -n database

kubectl apply -f pooler.yaml -n database

kubectl logs payment-db-1 -n database | grep "archive"

helm upgrade --install loki grafana/loki-stack \
  --namespace monitoring \
  --create-namespace \
  -f loki-stack-values.yaml

# نصب Prometheus و Grafana
helm upgrade --install prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f kube-prometheus-stack-values.yaml
# Backup 

# create BaseBackup
kubectl apply -f backup.yaml -n database

kubectl apply -f pitr-cluster.yaml -n database

cd recovery-app
docker build -t recovery-app:v1 . 
kind load docker-image recovery-app:v1  --name takhfifan
cd ..
kubectl apply -f k8s-manifest.yaml -n database


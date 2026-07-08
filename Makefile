# Makefile — local Kubernetes parity workflow (see docs/kubernetes-primer.md)
CLUSTER := annotated-maps
NS := annotated-maps
CHART := deploy/helm/annotated-maps
INGRESS_NGINX_VERSION := controller-v1.11.2
METRICS_SERVER_VERSION := v0.7.2
PROD_PLACEHOLDER_DB := postgis://placeholder:pw@example.com:5432/placeholder

.PHONY: kind-up deploy kind-down helm-checks

kind-up: ## Create the local cluster + ingress-nginx + metrics-server
	kind create cluster --name $(CLUSTER) --config deploy/kind/cluster.yaml
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/$(INGRESS_NGINX_VERSION)/deploy/static/provider/kind/deploy.yaml
	kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/$(METRICS_SERVER_VERSION)/components.yaml
	kubectl -n kube-system patch deployment metrics-server --type=json \
		-p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl -n ingress-nginx wait --for=condition=Available deployment/ingress-nginx-controller --timeout=180s

deploy: ## Build images, load into kind, install/upgrade the release
	docker build -f backend/Dockerfile -t annotated-maps-api:dev .
	docker build -f frontend/Dockerfile -t annotated-maps-web:dev frontend
	kind load docker-image annotated-maps-api:dev --name $(CLUSTER)
	kind load docker-image annotated-maps-web:dev --name $(CLUSTER)
	helm upgrade --install annotated-maps $(CHART) -n $(NS) --create-namespace --wait --timeout 5m

kind-down: ## Delete the local cluster (removes everything)
	kind delete cluster --name $(CLUSTER)

helm-checks: ## Static chart verification — same commands CI runs
	helm lint $(CHART)
	helm lint $(CHART) -f $(CHART)/values-prod.yaml --set secrets.databaseUrl=$(PROD_PLACEHOLDER_DB)
	helm plugin list | grep -q unittest || helm plugin install https://github.com/helm-unittest/helm-unittest --verify=false
	helm unittest $(CHART)
	helm template annotated-maps $(CHART) | kubeconform -strict -summary -kubernetes-version 1.30.0
	helm template annotated-maps $(CHART) -f $(CHART)/values-prod.yaml --set secrets.databaseUrl=$(PROD_PLACEHOLDER_DB) | kubeconform -strict -summary -kubernetes-version 1.30.0

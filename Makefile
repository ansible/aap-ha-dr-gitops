PYTHON ?= python3
DEPLOYMENT ?= examples/aws-rosa-pair
CLUSTER ?=
LAYER ?=
COLLECTION = operations/ansible_collections/aap/hadr_ops
export ANSIBLE_COLLECTIONS_PATH := $(CURDIR)/operations:$(CURDIR)/.local/collections

.PHONY: help validate configure render deployment-inputs gitops-install gitops-rbac apply-layer eso-identity postgres-admin-secret status ready ops-inventory ops-install ops-check preflight rgw-setup
help:
	@echo 'Local: validate configure render ops-inventory ops-install ops-check'
	@echo 'Cluster: gitops-install gitops-rbac apply-layer eso-identity postgres-admin-secret status ready'
	@echo 'Operations: preflight rgw-setup'
	@echo 'Set DEPLOYMENT=path CLUSTER=cluster_id LAYER=eso|odf|cnpg|platform'

validate:
	$(PYTHON) scripts/validate.py "$(DEPLOYMENT)"
configure:
	$(PYTHON) tools/hadr_inventory/configure.py "$(DEPLOYMENT)"
render:
	$(PYTHON) tools/hadr_inventory/render.py "$(DEPLOYMENT)"
deployment-inputs:
	$(PYTHON) scripts/validate.py "$(DEPLOYMENT)" --deploy

gitops-install gitops-rbac eso-identity status:
	$(PYTHON) scripts/bootstrap.py $@ --deployment "$(DEPLOYMENT)" --cluster "$(CLUSTER)"
apply-layer ready:
	$(PYTHON) scripts/bootstrap.py $@ --deployment "$(DEPLOYMENT)" --cluster "$(CLUSTER)" --layer "$(LAYER)"
postgres-admin-secret:
	@PG_PASSWORD=$$(oc --context=$(CLUSTER) get secret aap-postgres-app -n aap -o jsonpath='{.data.password}' | base64 -d); \
	if [ -z "$$PG_PASSWORD" ]; then echo "CNPG secret aap-postgres-app not found"; exit 1; fi; \
	oc --context=$(CLUSTER) create secret generic postgres-admin-credentials -n aap \
		--from-literal=username=postgres --from-literal=password="$$PG_PASSWORD" \
		--dry-run=client -o yaml | oc --context=$(CLUSTER) apply -f -

ops-inventory:
	$(PYTHON) tools/hadr_inventory/operations_inventory.py "$(DEPLOYMENT)"
ops-install:
	ansible-galaxy collection install -r operations/requirements.yml -p .local/collections
ops-check: ops-inventory
	ansible-playbook -i localhost, -c local operations/configuration.yml -e @"$(DEPLOYMENT)/operations/clusters.yml"
preflight: deployment-inputs ops-inventory
	ansible-playbook -i localhost, -c local $(COLLECTION)/playbooks/aap_preflight.yml -e @"$(DEPLOYMENT)/operations/clusters.yml" -e '{"autofix": false, "preflight_debug": false}'
rgw-setup: deployment-inputs ops-inventory
	ansible-playbook -i localhost, -c local $(COLLECTION)/playbooks/rgw_multisite_setup.yml -e @"$(DEPLOYMENT)/operations/clusters.yml"

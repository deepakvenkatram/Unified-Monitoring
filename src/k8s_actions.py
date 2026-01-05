import base64
import yaml
from kubernetes import client, config # Corrected import
from kubernetes.stream import stream
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.console import Console

# --- Client Initialization ---

def init_clients():
    """Initializes and returns Kubernetes API clients."""
    try:
        # Try loading in-cluster config first
        config.load_incluster_config()
        print("DEBUG: In-cluster config loaded successfully.")
    except config.ConfigException:
        try:
            # Fallback to kube-config file for local development
            config.load_kube_config()
            print("DEBUG: Kube-config loaded successfully.")
        except config.ConfigException:
            print("DEBUG: Failed to load any Kubernetes config.")
            print("Could not configure Kubernetes client. Please ensure you are running within a cluster or have a valid kubeconfig file.")
            return None, None, None

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    custom_objects = client.CustomObjectsApi()
    
    print(f"DEBUG: Clients initialized: core_v1={core_v1 is not None}, apps_v1={apps_v1 is not None}, custom_objects={custom_objects is not None}")
    return core_v1, apps_v1, custom_objects

# --- Value Parsing Helpers ---

def parse_cpu_value(cpu_str):
    """Parses a CPU string (e.g., '500m', '1', '2500n') into millicores."""
    if not cpu_str:
        return 0
    if cpu_str.endswith('n'):
        # Convert nanocores to millicores (1m = 1,000,000n)
        return int(cpu_str[:-1]) // 1000000
    if cpu_str.endswith('m'):
        return int(cpu_str[:-1])
    try:
        return int(cpu_str) * 1000
    except (ValueError, TypeError):
        # Handle cases where the value might not be a simple integer
        return 0

def parse_memory_value(mem_str):
    """Parses a memory string (e.g., '64Mi', '1Gi') into bytes."""
    if not mem_str:
        return 0
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
    mem_str = mem_str.strip()
    for unit, multiplier in units.items():
        if mem_str.endswith(unit):
            return int(mem_str[:-len(unit)]) * multiplier
    return int(mem_str)

# --- New Helper for Resource Monitoring ---

def get_all_pods_with_limits(core_v1_api):
    """
    Fetches all pods in all namespaces and extracts their resource limits.
    Returns a dictionary mapping (namespace, pod_name) to its limits.
    """
    pod_limits = {}
    try:
        all_pods = core_v1_api.list_pod_for_all_namespaces(watch=False).items
        for pod in all_pods:
            pod_key = (pod.metadata.namespace, pod.metadata.name)
            pod_limits[pod_key] = {"cpu": 0, "memory": 0}
            for container in pod.spec.containers:
                if container.resources and container.resources.limits:
                    limits = container.resources.limits
                    if limits.get("cpu"):
                        pod_limits[pod_key]["cpu"] += parse_cpu_value(limits["cpu"])
                    if limits.get("memory"):
                        pod_limits[pod_key]["memory"] += parse_memory_value(limits["memory"])
    except client.ApiException as e:
        print(f"Error fetching pod limits: {e}")
    return pod_limits


def get_pod_metrics(custom_objects_api, namespace="all"):
    """Fetches CPU and Memory metrics for pods in a given namespace or all namespaces."""
    pod_metrics = {}
    try:
        group = "metrics.k8s.io"
        version = "v1beta1"
        plural = "pods"
        
        if namespace == "all":
            metrics_list = custom_objects_api.list_cluster_custom_object(group, version, plural)
        else:
            metrics_list = custom_objects_api.list_namespaced_custom_object(group, version, plural, namespace)

        for item in metrics_list.get("items", []):
            pod_name = item["metadata"]["name"]
            namespace_name = item["metadata"]["namespace"]
            total_cpu = 0
            total_memory = 0
            for container in item.get("containers", []):
                total_cpu += parse_cpu_value(container["usage"]["cpu"])
                total_memory += parse_memory_value(container["usage"]["memory"])
            
            pod_metrics[(namespace_name, pod_name)] = {
                "cpu_usage_millicores": total_cpu,
                "memory_usage_bytes": total_memory
            }
    except client.ApiException as e:
        if e.status == 404:
            return {}, "Metrics API (metrics.k8s.io) not found. Is the Kubernetes Metrics Server installed?"
        return {}, f"Error fetching pod metrics: {e}"
    except Exception as e:
        return {}, f"An unexpected error occurred while fetching pod metrics: {e}"
        
    return pod_metrics, None


def get_pod_status(core_v1_api, custom_objects_api, namespace="all"):
    """
    Retrieves status, IP, and metrics for pods in a given namespace or all namespaces.
    """
    pods_info = []
    try:
        if namespace == "all":
            pods = core_v1_api.list_pod_for_all_namespaces(watch=False).items
        else:
            pods = core_v1_api.list_namespaced_pod(namespace, watch=False).items

        pod_metrics, error = get_pod_metrics(custom_objects_api, namespace)
        if error:
            # Non-fatal, we can still show status without metrics
            print(f"Warning: {error}")

        for pod in pods:
            pod_name = pod.metadata.name
            namespace_name = pod.metadata.namespace
            
            # Determine pod status
            status = pod.status.phase
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.state.waiting:
                        status = cs.state.waiting.reason
                        break
                    if cs.state.terminated:
                        status = cs.state.terminated.reason
                        break
            
            metrics = pod_metrics.get((namespace_name, pod_name), {})
            cpu_usage = metrics.get("cpu_usage_millicores", 0)
            mem_usage = metrics.get("memory_usage_bytes", 0)

            pods_info.append({
                "name": pod_name,
                "namespace": namespace_name,
                "status": status,
                "ip": pod.status.pod_ip,
                "cpu": f"{cpu_usage}m",
                "memory": f"{mem_usage // 1024**2}Mi",
                "container_statuses": pod.status.container_statuses
            })
    except client.ApiException as e:
        return [], f"Error fetching pod status: {e}"
    
    return pods_info, None


def get_deployment_status(core_v1_api, apps_v1_api, custom_objects_api, namespace="all"):
    """
    Retrieves status and aggregated metrics for deployments in a given namespace or all namespaces.
    """
    deployments_info = []
    try:
        if namespace == "all":
            deployments = apps_v1_api.list_deployment_for_all_namespaces(watch=False).items
        else:
            deployments = apps_v1_api.list_namespaced_deployment(namespace, watch=False).items

        pod_metrics, error = get_pod_metrics(custom_objects_api, namespace)
        if error:
            print(f"Warning: {error}")

        for dep in deployments:
            selector = dep.spec.selector.match_labels
            selector_str = ",".join([f"{k}={v}" for k, v in selector.items()])
            
            # Find pods belonging to this deployment
            pods = core_v1_api.list_namespaced_pod(dep.metadata.namespace, label_selector=selector_str).items
            
            total_cpu = 0
            total_memory = 0
            for pod in pods:
                metrics = pod_metrics.get((pod.metadata.namespace, pod.metadata.name), {})
                total_cpu += metrics.get("cpu_usage_millicores", 0)
                total_memory += metrics.get("memory_usage_bytes", 0)

            deployments_info.append({
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas,
                "pod_count": len(pods),
                "cpu": total_cpu,
                "memory": total_memory // 1024**2, # Convert to Mi
                "conditions": dep.status.conditions # Include conditions for deployment health check
            })
    except client.ApiException as e:
        return [], f"Error fetching deployment status: {e}"
        
    return deployments_info, None


# --- Other K8s Actions (unchanged from previous versions) ---

def get_node_info(core_v1_api):
    nodes_info = []
    try:
        nodes = core_v1_api.list_node().items
        for node in nodes:
            status = "Unknown"
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "Ready" if condition.status == "True" else "NotReady"
                    break
            
            roles = [key.split('/')[-1] for key in node.metadata.labels if key.startswith("node-role.kubernetes.io/")]
            
            nodes_info.append({
                "name": node.metadata.name,
                "status": status,
                "roles": ", ".join(roles) or "<none>",
                "ip": node.status.addresses[0].address,
                "version": node.status.node_info.kubelet_version
            })
    except client.ApiException as e:
        print(f"Error fetching node info: {e}")
    return nodes_info

def list_namespaces(core_v1_api):
    namespaces = []
    try:
        ns_list = core_v1_api.list_namespace().items
        for ns in ns_list:
            namespaces.append({
                "name": ns.metadata.name,
                "status": ns.status.phase
            })
    except client.ApiException as e:
        print(f"Error fetching namespaces: {e}")
    return namespaces

def get_pod_logs(core_v1_api, namespace, pod_name, container=None, since_seconds=None, tail_lines=None):
    try:
        return core_v1_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            since_seconds=since_seconds,
            tail_lines=tail_lines, # Added tail_lines
            _preload_content=True
        )
    except client.ApiException as e:
        return f"Error fetching logs for pod {pod_name}: {e.reason}"

def get_events(core_v1_api, limit=20):
    events_info = []
    try:
        events = core_v1_api.list_event_for_all_namespaces(limit=limit, _request_timeout=5).items
        # Sort events by last timestamp
        events.sort(key=lambda x: x.last_timestamp or x.event_time, reverse=True)
        
        for event in events:
            events_info.append({
                "last_seen": (event.last_timestamp or event.event_time).strftime('%H:%M:%S'),
                "type": event.type,
                "reason": event.reason,
                "object": f"{event.involved_object.kind}/{event.involved_object.name}",
                "message": event.message
            })
    except client.ApiException as e:
        return [], f"Error fetching events: {e}"
    return events_info, None

def scale_deployment(apps_v1_api, namespace, deployment_name, replicas):
    try:
        body = {"spec": {"replicas": replicas}}
        apps_v1_api.patch_namespaced_deployment_scale(deployment_name, namespace, body)
        return True, f"Deployment {deployment_name} scaled to {replicas} replicas."
    except client.ApiException as e:
        return False, f"Error scaling deployment: {e.reason}"

# ... (all other functions like describe_resource, get_*_yaml, etc. remain the same)
def describe_resource(core_v1_api, apps_v1_api, resource_type, name, namespace=None):
    try:
        if resource_type == "Pod":
            return core_v1_api.read_namespaced_pod(name, namespace, pretty=True), None
        elif resource_type == "Deployment":
            return apps_v1_api.read_namespaced_deployment(name, namespace, pretty=True), None
        elif resource_type == "Service":
            return core_v1_api.read_namespaced_service(name, namespace, pretty=True), None
        elif resource_type == "Node":
            return core_v1_api.read_node(name, pretty=True), None
    except client.ApiException as e:
        return None, f"Error describing resource: {e.reason}"

def _get_resource_as_yaml(read_func, **kwargs):
    try:
        resource = read_func(**kwargs, _preload_content=False)
        return yaml.dump(yaml.safe_load(resource.data)), None
    except client.ApiException as e:
        return None, f"Error fetching resource YAML: {e.reason}"

def get_pod_yaml(core_v1_api, namespace, name):
    return _get_resource_as_yaml(core_v1_api.read_namespaced_pod, name=name, namespace=namespace)

def get_deployment_yaml(apps_v1_api, namespace, name):
    return _get_resource_as_yaml(apps_v1_api.read_namespaced_deployment, name=name, namespace=namespace)

def get_node_yaml(core_v1_api, name):
    return _get_resource_as_yaml(core_v1_api.read_node, name=name)

def get_services(core_v1_api, namespace):
    services_info = []
    try:
        if namespace == "all":
            services = core_v1_api.list_service_for_all_namespaces().items
        else:
            services = core_v1_api.list_namespaced_service(namespace).items
        
        for svc in services:
            services_info.append({
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "external_ip": ", ".join(ip.ip for ip in svc.status.load_balancer.ingress) if svc.status.load_balancer.ingress else "<none>",
                "ports": ", ".join([f"{p.port}:{p.node_port}/TCP" if p.node_port else f"{p.port}/TCP" for p in svc.spec.ports])
            })
    except client.ApiException as e:
        return [], f"Error fetching services: {e.reason}"
    return services_info, None

def get_resource_quotas(core_v1_api, namespace):
    quotas_info = []
    try:
        quotas = core_v1_api.list_namespaced_resource_quota(namespace).items
        for q in quotas:
            quotas_info.append({
                "name": q.metadata.name,
                "hard": q.spec.hard,
                "used": q.status.used
            })
    except client.ApiException as e:
        print(f"Error fetching resource quotas: {e}")
    return quotas_info

def get_configmaps(core_v1_api, namespace):
    cm_info = []
    try:
        if namespace == "all":
            cms = core_v1_api.list_config_map_for_all_namespaces().items
        else:
            cms = core_v1_api.list_namespaced_config_map(namespace).items
        for cm in cms:
            cm_info.append({"name": cm.metadata.name, "data": cm.data})
    except client.ApiException as e:
        return [], f"Error fetching ConfigMaps: {e.reason}"
    return cm_info, None

def get_secrets(core_v1_api, namespace):
    secrets_info = []
    try:
        if namespace == "all":
            secrets = core_v1_api.list_secret_for_all_namespaces().items
        else:
            secrets = core_v1_api.list_namespaced_secret(namespace).items
        for s in secrets:
            decoded_data = {}
            if s.data:
                for k, v in s.data.items():
                    try:
                        decoded_data[k] = base64.b64decode(v).decode('utf-8')
                    except:
                        decoded_data[k] = "---<binary>---"
            secrets_info.append({"name": s.metadata.name, "type": s.type, "data": decoded_data})
    except client.ApiException as e:
        return [], f"Error fetching Secrets: {e.reason}"
    return secrets_info, None

def get_persistent_volumes(core_v1_api):
    pv_info = []
    try:
        pvs = core_v1_api.list_persistent_volume().items
        for pv in pvs:
            pv_info.append({
                "name": pv.metadata.name,
                "capacity": pv.spec.capacity.get('storage', 'N/A'),
                "access_modes": ", ".join(pv.spec.access_modes),
                "status": pv.status.phase,
                "claim": pv.spec.claim_ref.name if pv.spec.claim_ref else "",
                "storage_class": pv.spec.storage_class_name
            })
    except client.ApiException as e:
        return [], f"Error fetching PVs: {e.reason}"
    return pv_info, None

def get_persistent_volume_claims(core_v1_api, namespace):
    pvc_info = []
    try:
        if namespace == "all":
            pvcs = core_v1_api.list_persistent_volume_claim_for_all_namespaces().items
        else:
            pvcs = core_v1_api.list_namespaced_persistent_volume_claim(namespace).items
        for pvc in pvcs:
            pvc_info.append({
                "name": pvc.metadata.name,
                "status": pvc.status.phase,
                "volume": pvc.spec.volume_name,
                "capacity": pvc.status.capacity.get('storage', 'N/A') if pvc.status.capacity else "N/A",
                "access_modes": ", ".join(pvc.spec.access_modes),
                "storage_class": pvc.spec.storage_class_name
            })
    except client.ApiException as e:
        return [], f"Error fetching PVCs: {e.reason}"
    return pvc_info, None

def patch_deployment_image(apps_v1_api, namespace, deployment_name, container_name, new_image):
    try:
        patch = [{"op": "replace", "path": f"/spec/template/spec/containers/0/image", "value": new_image}]
        # This is a simplified patch assuming the container is the first one.
        # A more robust solution would find the container index by name.
        apps_v1_api.patch_namespaced_deployment(deployment_name, namespace, body=patch)
        return True, f"Deployment {deployment_name} image updated to {new_image}."
    except client.ApiException as e:
        return False, f"Error patching deployment: {e.reason}"

def patch_deployment_resources(apps_v1_api, namespace, deployment_name, container_name, new_resources):
    try:
        patch = [{"op": "replace", "path": f"/spec/template/spec/containers/0/resources", "value": new_resources}]
        apps_v1_api.patch_namespaced_deployment(deployment_name, namespace, body=patch)
        return True, f"Deployment {deployment_name} resources updated."
    except client.ApiException as e:
        return False, f"Error patching deployment resources: {e.reason}"

def exec_shell_in_pod(core_v1_api, namespace, pod_name, container_name):
    exec_command = ['/bin/sh']
    try:
        resp = stream(core_v1_api.connect_get_namespaced_pod_exec,
                      pod_name,
                      namespace,
                      container=container_name,
                      command=exec_command,
                      stderr=True, stdin=True,
                      stdout=True, tty=True,
                      _preload_content=False)
        
        # This part is tricky in a non-interactive script.
        # The original implementation might have more complex handling for raw terminal modes.
        # For now, we just print the output.
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                print(f"STDOUT: {resp.read_stdout()}")
            if resp.peek_stderr():
                print(f"STDERR: {resp.read_stderr()}")
        resp.close()

    except client.ApiException as e:
        print(f"Error executing shell in pod: {e.reason}")
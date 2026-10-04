import sys, types, json, importlib.util
from aiohttp import web
srv = types.ModuleType("server")
class PS: pass
PS.instance = types.SimpleNamespace(routes=web.RouteTableDef())
srv.PromptServer = PS
sys.modules["server"] = srv
spec = importlib.util.spec_from_file_location("lrp", sys.argv[1] + "/__init__.py", submodule_search_locations=[sys.argv[1]])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.HERE = sys.argv[2]  # pretend we live in custom_nodes
print(json.dumps(m._bench(30, 1.5), indent=1))
data, rec = m.render({"enc": "gpu", "exposure": 0.3, "clarity": 0.6})
open(sys.argv[3], "wb").write(data); print(rec)

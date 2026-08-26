import ast
import sys

def analyze():
    with open('app.py', 'r', encoding='utf-8') as f:
        code = f.read()
    
    tree = ast.parse(code)
    
    # Simple check for undefined names or attribute errors
    # Let's collect all defined functions and global variables
    defined_names = set(dir(__builtins__))
    defined_names.update(['customtkinter', 'ctk', 'subprocess', 'threading', 'os', 'sys', 're', 'shutil'])
    
    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.errors = []
            self.current_class = None
            self.current_function = None
            self.local_scopes = []
            
        def visit_ClassDef(self, node):
            old_class = self.current_class
            self.current_class = node.name
            # add class name to defined names
            defined_names.add(node.name)
            self.generic_visit(node)
            self.current_class = old_class
            
        def visit_FunctionDef(self, node):
            old_func = self.current_function
            self.current_function = node.name
            # arguments
            local_vars = set(arg.arg for arg in node.args.args)
            if node.args.vararg:
                local_vars.add(node.args.vararg.arg)
            if node.args.kwarg:
                local_vars.add(node.args.kwarg.arg)
                
            self.local_scopes.append(local_vars)
            
            # check body
            for stmt in node.body:
                self.visit(stmt)
                
            self.local_scopes.pop()
            self.current_function = old_func
            
        def visit_Assign(self, node):
            # register targets in current scope if any
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if self.local_scopes:
                        self.local_scopes[-1].add(target.id)
                    else:
                        defined_names.add(target.id)
            self.generic_visit(node)
            
        def visit_Import(self, node):
            for name in node.names:
                alias = name.asname or name.name.split('.')[0]
                if self.local_scopes:
                    self.local_scopes[-1].add(alias)
                else:
                    defined_names.add(alias)
                    
        def visit_ImportFrom(self, node):
            for name in node.names:
                alias = name.asname or name.name
                if self.local_scopes:
                    self.local_scopes[-1].add(alias)
                else:
                    defined_names.add(alias)
                    
        def visit_Name(self, node):
            # check if Name is loaded and not defined
            if isinstance(node.ctx, ast.Load):
                # check local scopes
                is_defined = False
                for scope in reversed(self.local_scopes):
                    if node.id in scope:
                        is_defined = True
                        break
                if not is_defined and node.id not in defined_names:
                    self.errors.append(f"Line {node.lineno}: Undefined name '{node.id}'")
                    
    visitor = Visitor()
    visitor.visit(tree)
    
    if visitor.errors:
        print("Potential Undefined Names found:")
        for err in visitor.errors:
            print(err)
    else:
        print("No simple undefined names found!")

if __name__ == "__main__":
    analyze()

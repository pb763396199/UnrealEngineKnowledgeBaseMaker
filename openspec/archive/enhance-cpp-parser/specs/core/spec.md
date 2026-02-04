# Spec Delta: C++ Parser Enhancement

## ADDED Requirements

### Requirement: Multiple Inheritance Parsing
The C++ parser SHALL extract all parent classes from a class declaration.

#### Scenario: Class with multiple inheritance
- **GIVEN** a C++ class declaration with multiple parents: `class A : public B, public IInterface, public IOther`
- **WHEN** the parser processes the declaration
- **THEN** the parser SHALL:
  - Set `parent_class` to the first non-interface parent (e.g., "B")
  - Set `parent_classes` to all parents ["B", "IInterface", "IOther"]
  - Set `interfaces` to all I-prefixed parents ["IInterface", "IOther"]

### Requirement: Namespace Detection
The C++ parser SHALL detect and record the namespace path for each class.

#### Scenario: Nested namespace (traditional syntax)
- **GIVEN** a class wrapped in nested namespaces:
  ```cpp
  namespace UE {
      namespace Core {
          class Log {};
      }
  }
  ```
- **WHEN** the parser processes the class
- **THEN** `ClassInfo.namespace` SHALL be "UE::Core"

#### Scenario: Nested namespace (C++17 syntax)
- **GIVEN** a class wrapped in C++17 namespace syntax:
  ```cpp
  namespace UE::Core {
      class Log {};
  }
  ```
- **WHEN** the parser processes the class
- **THEN** `ClassInfo.namespace` SHALL be "UE::Core"

### Requirement: Property Parsing (Basic)
The C++ parser SHALL extract UPROPERTY declarations from class bodies.

#### Scenario: Simple property
- **GIVEN** a property declaration:
  ```cpp
  UPROPERTY()
  int32 MyProperty;
  ```
- **WHEN** the parser processes the class body
- **THEN** the parser SHALL add a `PropertyInfo` with:
  - `name = "MyProperty"`
  - `type = "int32"`
  - `is_uproperty = True`

#### Scenario: Property without UPROPERTY
- **GIVEN** a property declaration without macro:
  ```cpp
  int32 MyProperty;
  ```
- **WHEN** the parser processes the class body
- **THEN** the parser SHALL add a `PropertyInfo` with:
  - `name = "MyProperty"`
  - `type = "int32"`
  - `is_uproperty = False`

#### Scenario: UE5 container types
- **GIVEN** a property with UE5 type:
  ```cpp
  TArray<FString> MyArray;
  ```
- **WHEN** the parser processes the class body
- **THEN** `PropertyInfo.type` SHALL be "TArray<FString>"

### Requirement: Method-Class Association
The C++ parser SHALL associate member functions with their containing class.

#### Scenario: Class with methods
- **GIVEN** a class definition with methods:
  ```cpp
  class AActor : public AObject {
  public:
      void Tick(float DeltaTime);
      void BeginPlay();
  };
  ```
- **WHEN** the parser processes the class body
- **THEN** the parser SHALL:
  - Set `FunctionInfo.class_name = "AActor"` for each method
  - Add method signatures to `ClassInfo.methods` list
  - Methods list SHALL contain: ["void Tick(float DeltaTime)", "void BeginPlay()"]

## CHANGED Requirements

### Requirement: ClassInfo Data Structure
The `ClassInfo.properties` field type SHALL change from `List[str]` to `List[PropertyInfo]`.

#### Breaking Change Note
Existing pickle files with old `List[str]` format will need regeneration.

## REMOVED Requirements
None

---

# Implementation Notes

## Data Structure Changes

### New PropertyInfo Dataclass
```python
@dataclass
class PropertyInfo:
    """属性信息（基础版本）"""
    name: str
    type: str
    is_uproperty: bool = False
```

### Updated ClassInfo
```python
@dataclass
class ClassInfo:
    # ... existing fields ...
    parent_classes: List[str] = field(default_factory=list)  # NEW
    interfaces: List[str] = field(default_factory=list)       # WILL BE FILLED
    methods: List[str] = field(default_factory=list)         # WILL BE FILLED
    properties: List[PropertyInfo] = field(default_factory=list)  # CHANGED TYPE
    namespace: str = ""                                       # WILL BE FILLED
```

## Parser Changes

### Class Body Parsing
The parser needs to:
1. Find class declaration line
2. Track opening/closing braces to find class body end
3. Parse class body content for methods and properties
4. Handle nested classes (inner classes)

### Namespace Stack
- Use a stack to track current namespace context
- Push on `namespace`, pop on closing `}`
- Build full path with `::` separator

## Performance Considerations
- Block-level parsing may increase parsing time by 10-20%
- Consider caching results for frequently parsed files

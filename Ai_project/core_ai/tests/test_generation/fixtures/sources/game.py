from typing import List

# ---------------------------------------------------------
# 1. Base Class 
# ---------------------------------------------------------
class Person:
    def __init__(self, name: str, id_number: int):
        self.name = name
        self.id_number = id_number

# ---------------------------------------------------------
# 2. Inheritance 
# ---------------------------------------------------------
class Professor(Person):
    def __init__(self, name: str, id_number: int, specialty: str):
        super().__init__(name, id_number)
        self.specialty = specialty

class Student(Person):
    # متغير على مستوى الكلاس (Class Attribute) لتتبع عدد الطلاب
    total_students_count = 0 

    def __init__(self, name: str, id_number: int, major: str):
        super().__init__(name, id_number)
        self.major = major
        self.courses: List['Course'] = []
        Student.total_students_count += 1 # زيادة العداد عند إنشاء طالب جديد

    # [إضافة] Class Method لإرجاع عدد الطلاب الإجمالي
    @classmethod
    def get_total_students(cls) -> int:
        return cls.total_students_count

    # [تعديل] تعديل الدالة لتشمل شروط التحقق (Validation)
    def enroll(self, course: 'Course') -> bool:
        if len(self.courses) >= 5:
            print(f"عذراً {self.name}، لقد وصلت للحد الأقصى من المواد (5).")
            return False
            
        if course in self.courses:
            print(f"الطالب {self.name} مسجل بالفعل في مادة {course.name}.")
            return False
            
        self.courses.append(course)
        course.add_student(self)
        return True

    # [إضافة] دالة جديدة لحذف مادة
    def drop_course(self, course: 'Course'):
        if course in self.courses:
            self.courses.remove(course)
            course.remove_student(self) # تحديث القائمة في كلاس المادة أيضاً
            print(f"تم حذف مادة {course.name} للطالب {self.name}.")

# ---------------------------------------------------------
# 3. Association 
# ---------------------------------------------------------
class Course:
    def __init__(self, name: str, code: str):
        self.name = name
        self.code = code
        self.students: List[Student] = []

    def add_student(self, student: Student):
        if student not in self.students:
            self.students.append(student)

    # [إضافة] دالة مكملة لحذف الطالب من سجل المادة
    def remove_student(self, student: Student):
        if student in self.students:
            self.students.remove(student)

# ---------------------------------------------------------
# 4. Aggregation 
# ---------------------------------------------------------
class Department:
    def __init__(self, name: str):
        self.name = name
        self.professors: List[Professor] = [] 

    # [تعديل / حذف] تم حذف add_professor القديمة واستبدالها بالتالي:
    def hire_professor(self, professor: Professor):
        if professor not in self.professors:
            self.professors.append(professor)
            print(f"تم تعيين الدكتور {professor.name} في قسم {self.name}.")

    # [إضافة] دالة جديدة لإزالة ارتباط الأستاذ بالقسم
    def fire_professor(self, professor: Professor):
        if professor in self.professors:
            self.professors.remove(professor)
            print(f"تم إزالة الدكتور {professor.name} من قسم {self.name}.")

# ---------------------------------------------------------
# 5. Composition 
# ---------------------------------------------------------
class University:
    def __init__(self, name: str):
        self.name = name
        self.departments: List[Department] = [] 

    def create_department(self, dept_name: str) -> Department:
        # التحقق من عدم وجود قسم بنفس الاسم مسبقاً
        for dept in self.departments:
            if dept.name == dept_name:
                print(f"القسم {dept_name} موجود بالفعل!")
                return dept
                
        new_dept = Department(dept_name)
        self.departments.append(new_dept)
        return new_dept
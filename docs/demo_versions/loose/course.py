class Course:
    def __init__(self, title: str, capacity: int = 2):
        self.title = title
        self.capacity = capacity
        self.students = []

    def is_full(self) -> bool:
        return len(self.students) >= self.capacity

    def add_student(self, student):
        if self.is_full():
            raise ValueError("course is full")
        if student not in self.students:
            self.students.append(student)

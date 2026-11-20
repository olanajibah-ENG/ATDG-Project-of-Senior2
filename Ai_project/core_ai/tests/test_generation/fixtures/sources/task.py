# ==========================================
# 1. الكلاسات المساعدة (تم التعديل والإضافة)
# ==========================================

class Engine:
    """كلاس المحرك (تم تعديله: إضافة نوع الوقود)"""
    def __init__(self, horsepower: int, fuel_type: str):
        self.horsepower = horsepower
        self.fuel_type = fuel_type  # <-- خاصية جديدة

    # <-- تم تعديل الميثود
    def start(self):
        print(f"محرك يعمل بقوة {self.horsepower} حصان باستخدام وقود {self.fuel_type}!")


class GPS:
    """كلاس نظام الملاحة (كلاس جديد بالكامل)"""
    def __init__(self):
        self.is_active = False

    # <-- ميثود جديد
    def locate(self):
        self.is_active = True
        print("GPS: جاري تحديد الموقع... تم العثور على الوجهة.")


class Driver:
    """كلاس السائق (كلاس جديد بالكامل)"""
    def __init__(self, name: str, license_id: str):
        self.name = name
        self.license_id = license_id

    # <-- ميثود جديد
    def introduce(self):
        print(f"أنا السائق {self.name}، ورقم رخصتي: {self.license_id}")


# ==========================================
# 2. الكلاس الرئيسي (تم حذف الوراثة وتعديل التركيب)
# ==========================================

class Car:
    """كلاس السيارة (تم حذف الوراثة من Vehicle، وأصبح Standalone)"""
    
    def __init__(self, brand: str, model: str, horsepower: int, fuel_type: str):
        self.brand = brand
        self.model = model

        # ✅ Composition (تكوين) - لا يزال موجود مع Engine
        # تم تعديله ليستقبل الـ fuel_type الجديد
        self.engine = Engine(horsepower, fuel_type)

        # ✅ Composition (تكوين) - علاقة جديدة مع GPS
        self.gps = GPS()

        # ✅ Association (ارتباط) - علاقة جديدة مع Driver
        # السائق يُمرر من الخارج ولا تملكه السيارة
        self.driver = None 


    # <-- ميثود جديد (لربط السائق بالسيارة)
    def assign_driver(self, driver: Driver):
        self.driver = driver

    # <-- تم حذف ميثود (add_wheel) بالكامل من هنا

    # <-- تم تعديل الميثود ليتناسب مع الكلاسات الجديدة
    def drive(self):
        print(f"--- جاري تشغيل {self.brand} {self.model} ---")
        
        if self.driver:
            self.driver.introduce()
        else:
            print("تحذير: لا يمكن القيادة因为没有 سائق!")

        self.engine.start()
        self.gps.locate()
        print("السيارة انطلقت في الطريق.\n")


# ==========================================
# 3. تجربة الكود
# ==========================================

if __name__ == "__main__":
    # إنشاء السائق بشكل مستقل (Association)
    driver_ahmad = Driver("أحمد", "DL-998877")

    # إنشاء السيارة (تم حذف فكرة العجلات، وإضافة الوقود)
    my_car = Car(brand="مرسيدس", model="C200", horsepower=204, fuel_type="بنزين")

    # ربط السائق بالسيارة
    my_car.assign_driver(driver_ahmad)

    # تشغيل السيارة
    my_car.drive()
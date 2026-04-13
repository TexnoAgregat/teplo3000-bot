# --- FSM для добавления ---
class AddProduct(StatesGroup):
    name = State()
    price = State()
    description = State()
    brand = State()
    power = State()
    mount_type = State()
    quantity = State()
    photo = State()

@dp.message(F.text == "➕ Добавить товар")
async def add_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddProduct.name)
    await message.answer("Введите название:", reply_markup=types.ReplyKeyboardRemove())

@dp.message(AddProduct.name)
async def add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProduct.price)
    await message.answer("Цена (число):")

@dp.message(AddProduct.price)
async def add_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("Введите число!")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.description)
    await message.answer("Описание:")

@dp.message(AddProduct.description)
async def add_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddProduct.brand)
    await message.answer("Бренд (например, Baxi):")

@dp.message(AddProduct.brand)
async def add_brand(message: types.Message, state: FSMContext):
    await state.update_data(brand=message.text)
    await state.set_state(AddProduct.power)
    await message.answer("Мощность (кВт, целое число):")

@dp.message(AddProduct.power)
async def add_power(message: types.Message, state: FSMContext):
    try:
        power = int(message.text)
    except ValueError:
        await message.answer("Введите целое число!")
        return
    await state.update_data(power=power)
    await state.set_state(AddProduct.mount_type)
    await message.answer("Тип монтажа (настенный/напольный):")

@dp.message(AddProduct.mount_type)
async def add_mount(message: types.Message, state: FSMContext):
    await state.update_data(mount_type=message.text.lower())
    await state.set_state(AddProduct.quantity)
    await message.answer("Количество на складе:")

@dp.message(AddProduct.quantity)
async def add_quantity(message: types.Message, state: FSMContext):
    try:
        qty = int(message.text)
    except ValueError:
        await message.answer("Введите число!")
        return
    await state.update_data(quantity=qty, in_stock=(qty > 0))
    await state.set_state(AddProduct.photo)
    await message.answer("Отправьте фото (можно несколько). Когда закончите — отправьте команду /done")

@dp.message(AddProduct.photo, F.photo)
async def add_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"📸 Фото {len(photos)} добавлено. Отправьте ещё или /done")

@dp.message(Command("done"), AddProduct.photo)
async def add_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("name"):
        await message.answer("Ошибка: нет данных. Начните заново.")
        await state.clear()
        return
    async with async_session() as session:
        product = Product(
            name=data["name"],
            price=data["price"],
            description=data["description"],
            brand=data.get("brand", ""),
            power=data.get("power", 0),
            mount_type=data.get("mount_type", ""),
            quantity=data.get("quantity", 0),
            in_stock=data.get("in_stock", False)
        )
        session.add(product)
        await session.flush()
        photos = data.get("photos", [])
        for i, file_id in enumerate(photos):
            img = ProductImage(product_id=product.id, file_id=file_id, is_main=(i == 0))
            session.add(img)
        await session.commit()
    await message.answer(f"✅ Товар '{data['name']}' добавлен!", reply_markup=main_keyboard())
    await state.clear()
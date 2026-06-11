const mongoose = require('mongoose')

const connectDB = async () => {
  const { MONGO_URI } = process.env

  if (!MONGO_URI) {
    console.warn('MONGO_URI is not set. Skipping database connection.')
    return
  }

  try {
    await mongoose.connect(MONGO_URI)
    console.log('MongoDB connected')
  } catch (error) {
    console.error('MongoDB connection error:', error.message)
    process.exit(1)
  }
}

module.exports = connectDB
